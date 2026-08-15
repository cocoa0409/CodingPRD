# Owner-Operator Lease-Purchase Program API — Product Requirements Document

## 1. Introduction

A truckload carrier's lease-purchase program sits at an awkward intersection: it is simultaneously an equipment-finance product, a weekly payroll-grade settlement system, and an independent-contractor compliance regime. Drivers — legally independent contractors, not employees — take possession of carrier-owned trucks under multi-year lease terms, pay for the equipment out of weekly revenue, accumulate an escrow stake toward an end-of-term buyout, and operate under a revenue-guarantee promise that the carrier must honor without undermining the contractor relationship. When the paperwork, the money, or the classification posture drifts out of alignment, the carrier inherits legal exposure that dwarfs the value of any single truck.

This document specifies the Owner-Operator Lease-Purchase Program API, mounted under `/lease-program`. The service manages the full lifecycle from contractor onboarding and truck intake through weekly settlement, maintenance cost attribution, escrow accumulation, default and cure, termination or completion, and the final buyout transaction. Two design commitments run throughout. First, every financial figure is derived from a small number of pinned, deterministic calculation rules — the weekly settlement waterfall, the dual-basis (provisional versus final) maintenance deduction, the buyout pricing ladder — so that an operator disputing a statement can be shown exactly how every cent moved. Second, the system's notion of "now" is a logical clock under explicit administrative control rather than wall-clock time, so every temporal rule (document expiry, settlement-week closure, lease-term maturity, quote expiry) is reproducible and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID` identifies the acting user and `X-User-Role` names their operational role. A request missing either header, or presenting a role string outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes five roles, spelled exactly: `LeaseAdmin`, `SettlementClerk`, `ComplianceOfficer`, `MaintenanceCoordinator`, and `Driver`.

`LeaseAdmin`, `SettlementClerk`, `ComplianceOfficer`, and `MaintenanceCoordinator` are opaque operator identities. When `X-User-Role` is any one of these four, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `OwnerOperator`; ownership checks on any resource that references an `OwnerOperator` (directly or through a lease's `owner_operator_id`) compare that foreign-key field to `X-User-ID`. A `Driver` acting on a resource belonging to a different operator is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403).

Division of labor: the `LeaseAdmin` owns operators, trucks, lease agreements, lane offers, buyout-quote generation, and the logical clock. The `SettlementClerk` owns the settlement lifecycle and escrow disbursement. The `ComplianceOfficer` owns compliance-document intake and review. The `MaintenanceCoordinator` owns service bays and work orders. The `Driver` accepts or declines lane offers, disputes settlements, and responds to buyout quotes — always on their own lease. All five roles share read access to every retrieval endpoint.

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

List endpoints paginate via two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — OwnerOperator, Truck, LeaseAgreement, EscrowAccount, SettlementStatement, LaneAssignment, ServiceBay, MaintenanceWorkOrder, ComplianceDocument, BuyoutQuote — carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at` is the same format, refreshed on every mutation. `version` is an integer that starts at 1 and increments on every mutation of the resource, including mutations driven by system cascades rather than direct client writes.

A note on unknown fields: creation payloads that carry fields beyond the documented input set have those extras silently ignored — they are neither stored nor echoed.

### 2.5. The Logical Clock

The server maintains a logical clock distinct from wall-clock time. Before any administrative adjustment, the logical clock starts at exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. A `LeaseAdmin` moves the clock by issuing a test-driving request carrying `to_iso8601`; the server adopts that instant as the current logical time and answers with the new `current_utc` value. Every temporal comparison in the system — compliance-document expiry, settlement-week closure, lease-term maturity, buyout-quote expiry — reads this logical clock, not the machine clock.

### 2.6. Monetary Precision and Rounding

All monetary quantities are integer cents; the API never emits fractional-cent values. When a calculation produces a non-integer (the fuel line multiplies gallons by a per-gallon price; the provisional maintenance reserve multiplies miles by a fractional per-mile rate; the early-buyout fee multiplies by a fractional rate), the result is rounded half-up to whole cents. Critically, every deduction line on a settlement is rounded to whole cents individually before any summation takes place, and the settlement waterfall sums those already-rounded integer-cent lines; summing first and rounding the total is forbidden.

### 2.7. Optimistic Concurrency Control

Optimistic locking applies to exactly one write operation: creating a buyout quote. That request must carry `expected_lease_version`, the client-supplied value of the target lease's current `version` as last observed. If the lease's current `version` differs from `expected_lease_version` — because any write, including a prior quote creation, has advanced it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This check exists because a successfully created quote supersedes the lease's prior `GENERATED` quote and bumps the lease version, so a create carrying a previously observed version is by construction operating on a stale view of the lease. No other endpoint accepts a version field.

### 2.8. Validation Ordering

When a request fails for more than one reason, the surfaced error follows a fixed priority order. First, header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role permission and entity-backed ownership (`ERR_FORBIDDEN_ROLE`; `ERR_RESOURCE_NOT_OWNED` shares this tier). Third, existence of path identifiers and body foreign-key references, validated left-to-right — path first, then body — yielding the appropriate `ERR_{RESOURCE}_NOT_FOUND`. Fourth, state preconditions of the target resource (the per-endpoint 409 state errors such as `ERR_LEASE_NOT_IN_APPLICATION` or `ERR_SETTLEMENT_NOT_ISSUED`). Fifth, business-safety rules (independent-contractor classification on activation). Sixth, temporal rules (week-in-term, week-closed, lane-window validity, buyout timing, bay buffer). Seventh, uniqueness constraints. Eighth, cross-entity referential consistency beyond existence. Ninth, fiscal floors and caps.

### 2.9. Resource Topology and Cross-Aggregate Reads

The entity graph is flat: resources are peers joined by foreign keys, and no URL nests one resource beneath another. A `LeaseAgreement` references its `OwnerOperator` and `Truck`; settlements, lane assignments, work orders, and buyout quotes each reference their lease by `lease_id`; a `ComplianceDocument` references its operator; a work order references its `ServiceBay`. Reverse lookups are served by query-parameter filters on the list endpoints — for example, listing settlements with a `lease_id` filter returns that lease's statements, and the same pattern serves escrow accounts, lane assignments, work orders (which additionally accept a `service_bay_id` filter), compliance documents (filtered by `owner_operator_id`), and buyout quotes. The escrow relationship to its lease is one-to-one, so the escrow list filtered by `lease_id` returns an array of at most one element. Lease listings may be narrowed by `owner_operator_id`, `truck_id`, or `status`; several other listings accept a `status` filter in the same style.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Contractor and the Truck

A `LeaseAdmin` registers an independent contractor by submitting the operator's `legal_name` and `cdl_number`. The CDL number is unique across operators; a collision is rejected with `ERR_DUPLICATE_VALUE` (HTTP 409). The new operator's `classification_status` begins at `PENDING_REVIEW` — registration alone establishes nothing about compliance posture.

Fleet intake is likewise a `LeaseAdmin` duty. A truck enters the system with its `vin` (unique; collisions also yield `ERR_DUPLICATE_VALUE`), `year`, `make`, `model`, the `odometer_current` reading at intake, and the two powertrain-warranty coordinates: `powertrain_warranty_expires_on` (an ISO 8601 date or datetime) and `powertrain_warranty_mileage_limit` in miles. A newly added truck starts in `AVAILABLE` status. Truck lifecycle from there is driven by lease events: activation moves `AVAILABLE` → `LEASED`; termination or completion moves `LEASED` → `IN_RETURN`; a `LeaseAdmin` confirming physical return moves `IN_RETURN` → `RETURNED` (a confirm-return attempt on a truck not in `IN_RETURN` is rejected with `ERR_TRUCK_NOT_IN_RETURN`); and relisting moves `RETURNED` → `AVAILABLE` for the next lessee (relisting a truck not in `RETURNED` fails with `ERR_TRUCK_NOT_RETURNED`). The remaining exit is a sale: a successful buyout-acceptance moves `LEASED` → `SOLD`, which is terminal. Each of these transitions increments the truck's `version` and refreshes `updated_at`.

### 3.2. Compliance Documents and Contractor Classification

Independent-contractor classification is a living posture, not a one-time checkbox. A `ComplianceOfficer` submits a document for an operator with three inputs: the `owner_operator_id` it belongs to, the `doc_type` — one of `W9`, `OPERATING_AUTHORITY`, `INSURANCE_CERTIFICATE`, or `MEDICAL_CARD` — and the document's `expires_on` date. A fresh document starts in `SUBMITTED`.

Review is binary. Verification moves `SUBMITTED` → `VERIFIED`; rejection moves `SUBMITTED` → `REJECTED` and may record a `rejection_reason` (and on the reject action the clerk-equivalent `reason` input is accepted). Either action on a document no longer in `SUBMITTED` fails with `ERR_DOC_ALREADY_REVIEWED`. After any verify or reject, the system recomputes the operator's `classification_status`.

The classification rule is exact. The required set for a `VERIFIED` posture is `W9`, `OPERATING_AUTHORITY`, and `INSURANCE_CERTIFICATE` — a `MEDICAL_CARD` may be filed but is not part of the required set. When every required type has a `VERIFIED` document whose `expires_on` lies strictly after the current logical clock, the operator is `VERIFIED`. When any required document is `REJECTED`, or a required `VERIFIED` document has reached or passed its `expires_on`, the operator is `FLAGGED`. Anything in between — documents missing, still `SUBMITTED`, awaiting review — is `PENDING_REVIEW`. Each recompute that changes the posture increments the operator's `version`.

Expiry is evaluated lazily but reliably: whenever a compliance document is read, and whenever a classification check runs, a `VERIFIED` document whose `expires_on` has been reached or passed by the logical clock evaluates to `EXPIRED` — and that evaluation feeds the classification recompute, dropping a `VERIFIED` operator to `FLAGGED`. A `FLAGGED` operator returns to `VERIFIED` only when a replacement required document is verified and unexpired, restoring the full required set. `REJECTED` and `EXPIRED` are terminal states for a document; the remedy is a new submission, not a resurrection.

### 3.3. The Lease Agreement: Creation, Activation, and Terms

With an operator and a truck on file, a `LeaseAdmin` drafts the lease. The creation payload names the parties by `owner_operator_id` and `truck_id`, fixes the schedule with `start_date` and `term_weeks` (the term-end instant is the start date plus the term in weeks times seven days), and fixes the economics: `weekly_payment_cents` for the equipment lease, `escrow_weekly_contribution_cents` and `escrow_cap_cents` for the savings stake, `buyout_base_price_cents` as the scheduled term-end purchase price, and `min_revenue_guarantee_weekly_cents` as the carrier's weekly gross-revenue floor. The referenced operator must exist (`ERR_OPERATOR_NOT_FOUND`) and the referenced truck must exist (`ERR_TRUCK_NOT_FOUND`); beyond existence, the truck must be `AVAILABLE` with no other non-terminal lease attached, or the create fails with `ERR_TRUCK_NOT_AVAILABLE`.

A new lease is born in `APPLICATION` status with three counters at zero — `missed_payment_count`, `arrears_cents`, `total_payments_applied_cents` — and the `escrow_satisfied` flag `false`. In the same transaction the system creates the lease's companion `EscrowAccount` (one per lease, pointing back via its `lease_id`), starting in `ACCUMULATING` with `balance_cents`, `total_credited_cents`, `total_refunded_cents`, and `total_applied_cents` all zero.

Activation is the gate where compliance bites. A `LeaseAdmin` activates a lease that is still in `APPLICATION` (otherwise `ERR_LEASE_NOT_IN_APPLICATION`), and the activation additionally requires the operator's `classification_status` to be `VERIFIED` at that moment — a `PENDING_REVIEW` or `FLAGGED` posture rejects the activation with `ERR_COMPLIANCE_REQUIREMENTS_UNMET` (HTTP 422). Successful activation moves the lease `APPLICATION` → `ACTIVE`, flips the truck `AVAILABLE` → `LEASED`, and increments the lease `version`.

### 3.4. Weekly Settlement: Draft, Issue, Dispute, Finalize

Settlement is the heartbeat of the program. Each week, a `SettlementClerk` creates a statement for a lease by supplying `lease_id`, the `week_start_date` (a Monday, ISO 8601 date), the week's `gross_revenue_cents`, fuel activity as `fuel_gallons` (decimals allowed) at `fuel_price_cents_per_gallon`, the `insurance_weekly_cents` premium, the `miles_driven`, and optionally `load_declined_flag` (default `false`). Three guards apply at creation, on top of lease existence: the lease must be `ACTIVE` or `DEFAULTED` (`ERR_LEASE_NOT_ACTIVE`); the week must lie inside the lease term — from `start_date` up to but not including the term-end instant — or the create fails with `ERR_WEEK_OUT_OF_TERM`; and the week must be closed, meaning the current logical clock has reached `week_start_date` plus seven days, failing with `ERR_SETTLEMENT_WEEK_NOT_CLOSED` otherwise. One settlement may exist per lease per week: a second create for the same `(lease_id, week_start_date)` pair is rejected with `ERR_DUPLICATE_WEEK_SETTLEMENT`.

The new statement is a `DRAFT` whose computed lines are already populated on the provisional basis. `fuel_deduction_cents` is the product of `fuel_gallons` and `fuel_price_cents_per_gallon`, rounded half-up to whole cents. `maintenance_deduction_cents` on the provisional basis is a reserve accrual: `miles_driven` multiplied by 12.5 cents per mile, rounded half-up to whole cents. The revenue-guarantee line `guarantee_top_up_cents` is computed before the waterfall proper (see §3.5). The waterfall then allocates the settlement's funds — gross revenue plus any guarantee top-up — through five ordered steps, each capped by what remains: step one subtracts the fuel deduction; step two subtracts `insurance_weekly_cents`; step three subtracts the maintenance deduction; step four takes the escrow contribution as the smallest of the scheduled `escrow_weekly_contribution_cents`, the remaining room under the lease's `escrow_cap_cents` (the cap minus the escrow account's current balance, floored at zero), and the funds remaining after step three — this becomes `escrow_contribution_cents`; step five applies the lease payment as the lesser of `weekly_payment_cents` and the funds remaining after escrow, producing `lease_payment_applied_cents`. Escrow is deliberately senior to the lease payment. Whatever survives step five is the operator's `net_pay_cents`, never below zero. The `payment_short_flag` is computed at finalize time (below) and marks whether the applied lease payment fell short of the scheduled amount.

From `DRAFT`, a `SettlementClerk` issues the statement — `DRAFT` → `ISSUED` — provided the lease is `ACTIVE` or `DEFAULTED` (issuing a non-draft fails with `ERR_SETTLEMENT_NOT_DRAFT`; a wrong lease state fails with `ERR_LEASE_NOT_ACTIVE`). The operator then reviews: a `Driver` whose identity matches the lease's operator may dispute an `ISSUED` statement, moving `ISSUED` → `DISPUTED` (wrong state: `ERR_SETTLEMENT_NOT_ISSUED`; wrong operator: `ERR_RESOURCE_NOT_OWNED`). Dispute resolution is a clerk action: reissuing a `DISPUTED` statement accepts a `maintenance_deduction_override_cents` value and an optional `reason`, substitutes the override for the maintenance line, recomputes the waterfall (escrow, lease payment, net pay, short flag) on the provisional basis with that override, and returns the statement to `ISSUED` (reissuing anything not `DISPUTED` fails with `ERR_SETTLEMENT_NOT_DISPUTED`).

Finalize is where the provisional becomes actual. A `SettlementClerk` finalizes an `ISSUED` statement (wrong state: `ERR_SETTLEMENT_NOT_FINALIZABLE`; lease not `ACTIVE`/`DEFAULTED`: `ERR_LEASE_NOT_ACTIVE`). At finalize, `maintenance_deduction_cents` is recomputed on the final basis: the sum of `actual_cost_cents` across this lease's work orders that are `COMPLETED`, billed to the operator, and whose `completed_at` falls within the half-open week from `week_start_date` to `week_start_date` plus seven days. For identical inputs the two bases generally differ — a reserve accrual versus actual billed work. The waterfall reruns on the final basis, `payment_short_flag` is set true when the applied lease payment is less than `weekly_payment_cents`, and the finalize then touches three other aggregates in a fixed cascade. Link one: the escrow account is credited by the settlement's `escrow_contribution_cents` — `balance_cents` and `total_credited_cents` each increase by that amount. Link two: if the credit brings `balance_cents` to or above the lease's `escrow_cap_cents` — equality counts — the escrow account flips `ACCUMULATING` → `FULL`. Link three: that flip sets the lease's `escrow_satisfied` flag true, a latch that is never reset. Meanwhile the lease's payment ledger updates: a short payment increments `missed_payment_count` by one and adds the shortfall (the scheduled weekly payment minus the applied amount) to `arrears_cents`; short or not, `total_payments_applied_cents` grows by the applied amount. The statement's own `version` increments, as does every other resource the cascade touches.

Settlement end-states are `FINALIZED` and `CANCELLED`; the latter arrives only through lease termination, which sweeps every `DRAFT`, `ISSUED`, or `DISPUTED` statement of the lease into `CANCELLED`.

### 3.5. The Revenue Guarantee and Lane Assignments

The carrier's minimum-revenue promise is conditional, and the conditions are checked per settlement week. A week is guarantee-eligible when three facts all hold: the lease is `ACTIVE` (a `DEFAULTED` lease forfeits the guarantee), the week's `load_declined_flag` is false (an operator who declined a dispatched load voids that week's guarantee), and at least one lane assignment of the lease is `ACCEPTED` with a window covering the `week_start_date` — the lane's `start_date` on or before the week start and its `end_date` strictly after, under half-open window semantics. For an eligible week, `guarantee_top_up_cents` is the larger of zero and the guarantee floor minus the week's gross revenue; when gross revenue equals or exceeds `min_revenue_guarantee_weekly_cents`, the top-up is zero. An ineligible week always takes a top-up of zero.

Lane assignments begin as carrier offers. A `LeaseAdmin` offers a lane with the target `lease_id`, the `origin` and `destination`, a `weekly_commitment_cents`, and a window given by `start_date` (inclusive) and `end_date` (exclusive). The window must be nonempty — an `end_date` not strictly later than `start_date` is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 400). A fresh offer sits in `OFFERED`.

The operator responds. Acceptance — `OFFERED` → `ACCEPTED` — is a `Driver` action gated by five checks, surfaced in priority order: the lane must be `OFFERED` (`ERR_LANE_NOT_OFFERED`), the acting driver must own the lease (`ERR_RESOURCE_NOT_OWNED`), the lease must be `ACTIVE` or `DEFAULTED` (`ERR_LEASE_NOT_ACTIVE`), the new window must not overlap any other `ACCEPTED` lane of the same lease — windows are half-open, so a new window whose `start_date` equals an existing window's `end_date` is adjacency and permitted, while any strict crossing rejects with `ERR_LANE_WINDOW_OVERLAP` — and the commitment must meet the floor: `weekly_commitment_cents` of at least 50000 (five hundred dollars per week), failing with `ERR_LANE_COMMITMENT_BELOW_MIN`. Declining is simpler: an `OFFERED` lane owned by the acting driver moves `OFFERED` → `DECLINED`, terminal.

From `ACCEPTED`, a lane has three exits. A `LeaseAdmin` may revoke it (`ACCEPTED` → `REVOKED`; revoking a lane not `ACCEPTED` fails with `ERR_LANE_NOT_ACCEPTED`). A default declaration on the lease revokes every `ACCEPTED` lane as part of its cascade. And lease completion — whether by term-end completion or buyout acceptance — moves every `ACCEPTED` lane to `COMPLETED` and every `OFFERED` lane to `REVOKED`. Termination revokes both `OFFERED` and `ACCEPTED` lanes indiscriminately. `COMPLETED`, `DECLINED`, and `REVOKED` are all terminal.

The guarantee has a second-order interaction worth stating plainly: because default strips guarantee eligibility, declaring default on a lease not only revokes its `ACCEPTED` lanes (link one of the default cascade) but also recomputes every non-final settlement of that lease (link two, caused by link one) with `guarantee_top_up_cents` forced to zero and the waterfall and `net_pay_cents` recomputed accordingly.

### 3.6. Maintenance: Bays, Work Orders, and Warranty Attribution

The shop side starts with infrastructure. A `MaintenanceCoordinator` registers a service bay by its `bay_code` (unique; collisions draw `ERR_DUPLICATE_VALUE`) and `location`.

Booking a work order takes `lease_id`, `service_bay_id`, a `category` of `PREVENTIVE`, `REPAIR`, or `RECALL`, a free-text `description`, a booking window from `scheduled_start` (inclusive) to `scheduled_end` (exclusive), and an `estimated_cost_cents`. The window must be nonempty — `scheduled_end` not strictly after `scheduled_start` fails with `ERR_INVALID_DATE_RANGE` — and the lease must be `ACTIVE` or `DEFAULTED` (`ERR_LEASE_NOT_ACTIVE`). Bay scheduling honors a turnover buffer: against every existing booking of the same bay in `OPEN` or `COMPLETED` status (cancelled bookings free their windows), the new booking conflicts unless there is a gap of at least two hours between the windows on either side — that is, unless the new start is at or after the existing end plus two hours, or the new end is at or before the existing start minus two hours. A gap of exactly two hours is permitted; anything tighter is rejected with `ERR_BAY_WINDOW_CONFLICT`. A booked order is `OPEN`.

Completion is the attribution moment. Completing an `OPEN` order takes the `actual_cost_cents` and the `odometer_at_service` reading, stamps `completed_at` with the current logical clock, computes `billed_to`, and raises the truck's `odometer_current` to the larger of its prior value and the service reading. The billing rule: `RECALL` work is always `CARRIER`-billed; `PREVENTIVE` work is always `OPERATOR`-billed — preventive care is the operator's duty; `REPAIR` work is `WARRANTY`-billed when the `odometer_at_service` is at or below the truck's `powertrain_warranty_mileage_limit` and the `scheduled_start` is at or before the truck's `powertrain_warranty_expires_on` — both boundaries are inclusive — and `OPERATOR`-billed otherwise. Completing or cancelling an order no longer `OPEN` fails with `ERR_WORK_ORDER_NOT_OPEN`. Cancellation moves `OPEN` → `CANCELLED` and frees the bay window. Only `COMPLETED` orders billed to the operator feed the final maintenance basis of a settlement, matched to the week containing their `completed_at`.

### 3.7. Default, Cure, Termination, and Completion

A lease that cannot collect its weekly payment degrades by degrees. The finalize-time bookkeeping (§3.4) accumulates the evidence: each short payment bumps `missed_payment_count` and piles the shortfall into `arrears_cents`. When the count reaches three, the lease is default-eligible — a `LeaseAdmin` declares default on an `ACTIVE` lease (wrong state: `ERR_LEASE_NOT_ACTIVE`) whose `missed_payment_count` has reached at least three (otherwise `ERR_LEASE_NOT_DEFAULT_ELIGIBLE`), moving `ACTIVE` → `DEFAULTED`. The declaration cascades: every `ACCEPTED` lane of the lease is revoked, and — because the revocation strips guarantee eligibility — every `DRAFT`, `ISSUED`, or `DISPUTED` settlement is recomputed with its guarantee line zeroed and its waterfall and `net_pay_cents` re-derived. The lease `version` increments.

Default is curable. A `LeaseAdmin` cures a `DEFAULTED` lease (wrong state: `ERR_LEASE_NOT_DEFAULTED`) by submitting an `arrears_payment_cents` amount; a payment smaller than the current `arrears_cents` is rejected with `ERR_ARREARS_NOT_CLEARED` (HTTP 422). On success the lease returns `DEFAULTED` → `ACTIVE`, `arrears_cents` and `missed_payment_count` reset to zero, and any overpayment — the amount paid beyond the arrears — flows into escrow: the escrow balance rises by the overpayment, truncated at the lease's `escrow_cap_cents`, with `total_credited_cents` growing by the credited portion.

Termination is the hard exit, available from `APPLICATION`, `ACTIVE`, or `DEFAULTED` (terminating a lease already `COMPLETED` or `TERMINATED` fails with `ERR_LEASE_ALREADY_TERMINAL`). The cascade differs by starting state. From `ACTIVE` or `DEFAULTED`: the truck moves `LEASED` → `IN_RETURN`; escrow is applied to arrears — the applied amount is the lesser of the escrow balance and the arrears, the balance and `arrears_cents` each fall by that amount, and `total_applied_cents` grows by it; if any escrow balance remains after that application the account moves to `REFUND_PENDING`, otherwise to `CLOSED`; every `OFFERED` or `ACCEPTED` lane is revoked; and every `DRAFT`, `ISSUED`, or `DISPUTED` settlement is cancelled. From `APPLICATION` — a lease that never activated — the truck was never leased and is untouched, the escrow (balance zero) closes, non-final settlements cancel, and `OFFERED` lanes revoke.

Completion without purchase is the graceful exit. A `LeaseAdmin` completes an `ACTIVE` lease (wrong state: `ERR_LEASE_NOT_ACTIVE`) once the logical clock has reached the term end — the start date plus the term in weeks times seven days — failing with `ERR_LEASE_TERM_NOT_REACHED` before that. Completion moves the lease `ACTIVE` → `COMPLETED`, the truck `LEASED` → `IN_RETURN`, and the escrow account — whether `ACCUMULATING` or `FULL` — to `REFUND_PENDING` with its balance unchanged pending disbursement. `ACCEPTED` lanes complete; `OFFERED` lanes revoke. A `SettlementClerk` then disburses a `REFUND_PENDING` escrow: the full `balance_cents` is added to `total_refunded_cents`, the balance zeroes, and the account moves to `REFUNDED` (disbursing an account not in `REFUND_PENDING` fails with `ERR_ESCROW_NOT_REFUNDABLE`). `REFUNDED` and `CLOSED` are the escrow terminal states.

### 3.8. Buyout: Quote Generation, Pricing, and Acceptance

The purchase leg begins with a quote. A `LeaseAdmin` requests one with the `lease_id`, a `quote_kind` of `SCHEDULED` or `EARLY`, and — per §2.7 — an `expected_lease_version` carrying the lease's current `version` as last observed; a stale expectation is rejected with `ERR_STALE_VERSION` (HTTP 412). Two eligibility rules gate generation: a `SCHEDULED` quote requires the logical clock to have reached the term end, and any quote requires the lease to be `ACTIVE` or `DEFAULTED` — violations draw `ERR_BUYOUT_NOT_ELIGIBLE` (HTTP 422). Creating a quote supersedes any prior `GENERATED` quote of the same lease (which moves to `SUPERSEDED`, terminal) and increments the lease's `version` by one — the very mutation the OCC field guards against on a subsequent create.

Pricing is pinned to a four-step evaluation order, because price, arrears, and escrow credit interlock. Step one computes `quoted_price_cents`: a `SCHEDULED` quote takes exactly the lease's `buyout_base_price_cents`; an `EARLY` quote adds an early fee — the remaining whole weeks of the term (the term in weeks minus the whole weeks elapsed from `start_date` to the current logical clock, floored at zero) multiplied by `weekly_payment_cents` multiplied by one-tenth, with the product rounded half-up to whole cents. Step two snapshots the lease's current `arrears_cents` into `arrears_carried_cents`. Step three computes `escrow_credit_cents` as the lesser of the escrow account's current balance and the quoted price plus the carried arrears. Step four sets `amount_due_cents` to the quoted price plus carried arrears minus the escrow credit, floored at zero. The escrow balance is read at step three and is not refunded separately on acceptance — acceptance applies it. The quote's `expires_on` is stamped seven days after its creation.

The operator answers. Accepting requires the quote to be `GENERATED` (otherwise `ERR_QUOTE_NOT_GENERATED`), unexpired against the logical clock (`ERR_QUOTE_EXPIRED`, HTTP 409, once `expires_on` has been reached), initiated by the `Driver` who owns the lease (`ERR_RESOURCE_NOT_OWNED`), and on a lease that is `ACTIVE` or `DEFAULTED` (`ERR_LEASE_NOT_ACTIVE`). Acceptance is the second route to `COMPLETED`: the lease moves `ACTIVE` (or `DEFAULTED`) → `COMPLETED`, the truck `LEASED` → `SOLD`, and the escrow is applied to the purchase — the applied amount is the lesser of the balance and the quoted price plus arrears, the balance falls by it, `total_applied_cents` grows by it, and the account closes regardless of remainder, since the credit was priced into the amount due. `ACCEPTED` lanes complete; `OFFERED` lanes revoke. Declining — same ownership and `GENERATED` preconditions — simply moves the quote to `DECLINED`, terminal.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource — including all state-transition actions — return `200 OK`. All paths are mounted under `/lease-program`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/lease-program/owner-operators` | Register an owner-operator (classification starts `PENDING_REVIEW`) | LeaseAdmin |
| GET | `/lease-program/owner-operators/{id}` | Get one owner-operator (classification re-evaluated against the logical clock on read) | Any |
| POST | `/lease-program/trucks` | Add a truck to the fleet (status `AVAILABLE`) | LeaseAdmin |
| GET | `/lease-program/trucks/{id}` | Get one truck | Any |
| POST | `/lease-program/trucks/{id}/confirm-return` | Confirm physical truck return (`IN_RETURN` → `RETURNED`) | LeaseAdmin |
| POST | `/lease-program/trucks/{id}/relist` | Relist a returned truck (`RETURNED` → `AVAILABLE`) | LeaseAdmin |
| POST | `/lease-program/lease-agreements` | Create a lease (`APPLICATION`) and its escrow account (`ACCUMULATING`, balance 0) | LeaseAdmin |
| GET | `/lease-program/lease-agreements` | List lease agreements with optional filters | Any |
| GET | `/lease-program/lease-agreements/{id}` | Get one lease agreement | Any |
| POST | `/lease-program/lease-agreements/{id}/activate` | Activate an `APPLICATION` lease (requires operator `VERIFIED`) | LeaseAdmin |
| POST | `/lease-program/lease-agreements/{id}/declare-default` | Declare default on an `ACTIVE` lease with at least three missed payments | LeaseAdmin |
| POST | `/lease-program/lease-agreements/{id}/cure-default` | Cure a `DEFAULTED` lease by paying arrears; overpayment flows to escrow | LeaseAdmin |
| POST | `/lease-program/lease-agreements/{id}/terminate` | Terminate a non-terminal lease; escrow applied to arrears, truck to `IN_RETURN` when leased | LeaseAdmin |
| POST | `/lease-program/lease-agreements/{id}/complete` | Complete an `ACTIVE` lease at or after term end; escrow to `REFUND_PENDING` | LeaseAdmin |
| POST | `/lease-program/settlement-statements` | Create a weekly settlement in `DRAFT` with provisional computed lines | SettlementClerk |
| GET | `/lease-program/settlement-statements` | List settlements; `lease_id` filter is the foreign-key reverse lookup | Any |
| GET | `/lease-program/settlement-statements/{id}` | Get one settlement | Any |
| POST | `/lease-program/settlement-statements/{id}/issue` | Issue a `DRAFT` settlement to the operator | SettlementClerk |
| POST | `/lease-program/settlement-statements/{id}/dispute` | Operator disputes an `ISSUED` settlement (own lease only) | Driver |
| POST | `/lease-program/settlement-statements/{id}/reissue` | Clerk reissues a `DISPUTED` settlement with a maintenance override; waterfall recomputed | SettlementClerk |
| POST | `/lease-program/settlement-statements/{id}/finalize` | Finalize an `ISSUED` settlement: final maintenance basis, escrow credit cascade, missed-payment tracking | SettlementClerk |
| GET | `/lease-program/escrow-accounts` | List escrow accounts; `lease_id` filter yields at most one | Any |
| GET | `/lease-program/escrow-accounts/{id}` | Get one escrow account | Any |
| POST | `/lease-program/escrow-accounts/{id}/disburse` | Disburse a `REFUND_PENDING` escrow to the operator | SettlementClerk |
| POST | `/lease-program/lane-assignments` | Offer a lane to a lease (status `OFFERED`) | LeaseAdmin |
| GET | `/lease-program/lane-assignments` | List lane assignments; `lease_id` filter is the reverse lookup | Any |
| GET | `/lease-program/lane-assignments/{id}` | Get one lane assignment | Any |
| POST | `/lease-program/lane-assignments/{id}/accept` | Operator accepts an offered lane (ownership, lease state, overlap, floor checks) | Driver |
| POST | `/lease-program/lane-assignments/{id}/decline` | Operator declines an offered lane | Driver |
| POST | `/lease-program/lane-assignments/{id}/revoke` | Carrier revokes an `ACCEPTED` lane | LeaseAdmin |
| POST | `/lease-program/service-bays` | Register a service bay | MaintenanceCoordinator |
| GET | `/lease-program/service-bays/{id}` | Get one service bay | Any |
| POST | `/lease-program/maintenance-work-orders` | Book a work order into a bay (lease state, buffer conflict, window checks) | MaintenanceCoordinator |
| GET | `/lease-program/maintenance-work-orders` | List work orders; `lease_id` and `service_bay_id` filters are reverse lookups | Any |
| GET | `/lease-program/maintenance-work-orders/{id}` | Get one work order | Any |
| POST | `/lease-program/maintenance-work-orders/{id}/complete` | Complete an `OPEN` order: billing attribution, clock stamp, odometer raise | MaintenanceCoordinator |
| POST | `/lease-program/maintenance-work-orders/{id}/cancel` | Cancel an `OPEN` order, freeing the bay window | MaintenanceCoordinator |
| POST | `/lease-program/compliance-documents` | Submit a compliance document (status `SUBMITTED`) | ComplianceOfficer |
| GET | `/lease-program/compliance-documents` | List documents; read evaluates clock-based expiry | Any |
| GET | `/lease-program/compliance-documents/{id}` | Get one document (expiry evaluated against the logical clock) | Any |
| POST | `/lease-program/compliance-documents/{id}/verify` | Verify a `SUBMITTED` document; recompute operator classification | ComplianceOfficer |
| POST | `/lease-program/compliance-documents/{id}/reject` | Reject a `SUBMITTED` document; recompute operator classification | ComplianceOfficer |
| POST | `/lease-program/buyout-quotes` | Generate a buyout quote (OCC on lease version; supersedes prior `GENERATED` quotes) | LeaseAdmin |
| GET | `/lease-program/buyout-quotes` | List buyout quotes; `lease_id` filter is the reverse lookup | Any |
| GET | `/lease-program/buyout-quotes/{id}` | Get one buyout quote | Any |
| POST | `/lease-program/buyout-quotes/{id}/accept` | Operator accepts a `GENERATED`, unexpired quote: lease `COMPLETED`, truck `SOLD`, escrow applied and closed | Driver |
| POST | `/lease-program/buyout-quotes/{id}/decline` | Operator declines a `GENERATED` quote | Driver |
| POST | `/lease-program/_clock/set_current_utc` | Set the server's logical clock (test-driving capability) | LeaseAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_NOT_OWNED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_OPERATOR_NOT_FOUND` | 404 Not Found |
| `ERR_TRUCK_NOT_FOUND` | 404 Not Found |
| `ERR_LEASE_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ESCROW_NOT_FOUND` | 404 Not Found |
| `ERR_LANE_NOT_FOUND` | 404 Not Found |
| `ERR_BAY_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_DOC_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_LEASE_NOT_IN_APPLICATION` | 409 Conflict |
| `ERR_LEASE_NOT_ACTIVE` | 409 Conflict |
| `ERR_LEASE_NOT_DEFAULTED` | 409 Conflict |
| `ERR_LEASE_NOT_DEFAULT_ELIGIBLE` | 409 Conflict |
| `ERR_LEASE_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_LEASE_TERM_NOT_REACHED` | 409 Conflict |
| `ERR_TRUCK_NOT_AVAILABLE` | 409 Conflict |
| `ERR_TRUCK_NOT_IN_RETURN` | 409 Conflict |
| `ERR_TRUCK_NOT_RETURNED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_ISSUED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_DISPUTED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_FINALIZABLE` | 409 Conflict |
| `ERR_ESCROW_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_LANE_NOT_OFFERED` | 409 Conflict |
| `ERR_LANE_NOT_ACCEPTED` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_OPEN` | 409 Conflict |
| `ERR_DOC_ALREADY_REVIEWED` | 409 Conflict |
| `ERR_QUOTE_NOT_GENERATED` | 409 Conflict |
| `ERR_WEEK_OUT_OF_TERM` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_WEEK_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_WEEK_SETTLEMENT` | 409 Conflict |
| `ERR_DUPLICATE_VALUE` | 409 Conflict |
| `ERR_LANE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_LANE_COMMITMENT_BELOW_MIN` | 422 Unprocessable Entity |
| `ERR_BAY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_COMPLIANCE_REQUIREMENTS_UNMET` | 422 Unprocessable Entity |
| `ERR_ARREARS_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_BUYOUT_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
