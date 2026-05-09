# Used-Car Trading API — Product Requirements Document

## 1. Introduction

The used-car trading platform connects three constituencies whose interests have historically been hard to align inside a single online experience: sellers who need a credible way to advertise pre-owned vehicles, buyers who need confidence that the car on the listing matches the car in the driveway, and operators who carry the regulatory and financial risk of facilitating an ownership change. This document specifies the back-end API that mediates that relationship end-to-end — from VIN-keyed assessment through listing review, AUCTION bidding or FIXED_PRICE reservation, payment, vehicle-administration transfer, optional financing, post-sale warranty service, and dispute mediation.

The system is designed around the assumption that very little of the action is synchronous. Payments, credit checks, lender disbursements, and DMV outcomes all arrive asynchronously as external events, and the platform's correctness depends on processing each one exactly once while keeping the buyer's deposit accounting, the vehicle's ownership record, the listing's lifecycle, and any outstanding loan or warranty obligation in a single consistent picture. A second design pressure is reversibility: a transfer can fail at the DMV, a dispute can resolve in favour of the buyer, and the platform must be able to unwind a sale that has already settled — refund the buyer, restore the listing, void the warranty, cancel the loan disbursement claim, and restore the original ownership pointer — without leaving an orphan record.

The remainder of this document treats §2 as the contract layer (response shape, headers, common properties, concurrency rules, precision policy, and other cross-cutting principles) and §3 as the business-logic layer, where the workflows for assessment, listing, bidding, reservation, purchase, transfer, financing, warranty, and dispute are described in narrative form. §4 lists every endpoint as a concise method/path/role table; §5 enumerates every error identifier and its HTTP status. The hidden test suite is generated against the rules expressed throughout — implementers must therefore reconstruct each rule from the prose, not from any single reference table.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. Either missing yields `ERR_AUTH_MISSING` with HTTP 401. An unrecognised role string, or an `X-User-ID` that is empty or not a well-formed UUID, yields `ERR_AUTH_INVALID` with HTTP 401. When the headers are present and parseable but the role is not authorised to invoke the requested endpoint per the RBAC matrix in §4, the server returns `ERR_FORBIDDEN` with HTTP 403.

The platform recognises exactly four roles: `Seller`, `Buyer`, `Inspector`, and `PlatformAdmin`.

The interpretation of `X-User-ID` depends on the role. When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks on any resource that references a `Seller` (notably `Vehicle.ownership_seller_id`, `Listing.seller_id`, and `PurchaseOrder.seller_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer`; ownership checks on `Bid.buyer_id`, `Reservation.buyer_id`, `PurchaseOrder.buyer_id`, `Loan.buyer_id`, and any warranty claim, dispute case, or transfer case that traces back to one of those rows likewise compare to `X-User-ID`. When `X-User-Role` is `Inspector` or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `inspector_user_id` on `AssessmentReport` when an inspector finalises a report, or as `actor_id` on every `AuditLog` entry) but does not compare it to any entity's `id`.

A request that satisfies authentication and authorisation but targets a resource the caller does not own is rejected with `ERR_NOT_OWNER` and HTTP 403. This applies to all mutating operations (POST, PATCH, DELETE) on `Vehicle`, `Listing`, `Bid`, `Reservation`, `PurchaseOrder`, `Loan`, `WarrantyClaim`, and `DisputeCase` resources whose owner is the acting role.

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

List endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10 and the default `offset` is 0. The accepted range for `limit` is from 1 to 100 inclusive on both ends; `offset` must be at least 0. A value outside these ranges is rejected with `ERR_PAGINATION_INVALID` and HTTP 400. Lists are returned in ascending order of `created_at`, with ties broken by `id` (lexicographic). The `meta` block on list responses includes `limit`, `offset`, `total_count` (the total number of rows matching the filter, ignoring `limit`/`offset`), and `has_more` (a boolean that is true exactly when `offset + limit < total_count`).

### 2.4. Common Resource Properties

Most resources expose four server-managed fields. The `id` is a server-minted UUID v4 string with no type prefix; clients must never supply it. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set at insertion, `updated_at` is refreshed on every mutating operation that produces a new server-visible state. `version` is an integer that starts at 1 and increments by 1 on every mutation. The `Bid`, `Reservation`, `ExternalEvent`, and `AuditLog` entities are exceptions: they carry only `id` and `created_at` — neither `updated_at` nor `version` is present on those rows, which is appropriate because their state-bearing transitions are append-only or immutable observations rather than rewritable records.

### 2.5. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When supplied, the server compares it to the current persisted `version` for the target resource: a match performs the mutation and increments `version` by 1; a mismatch — meaning another writer has already advanced the row — is rejected with `ERR_VERSION_CONFLICT` and HTTP 409. When the field is omitted, the server applies the mutation without a concurrency check (last-writer-wins for that request). Endpoints whose target entity has no `version` field (`Bid`, `Reservation`, `ExternalEvent`, `AuditLog`) silently ignore the field if supplied.

### 2.6. Hierarchical Consistency and Cascading Side Effects

State changes on parent entities propagate to children, and several state changes on child entities propagate up to parents. Whenever a cascading mutation fires, every affected row has its `updated_at` refreshed and (where the row carries one) its `version` advanced by 1; this allows clients to detect that a row they had cached has moved underneath them. Concretely, a `PurchaseOrder` reaching `PAID` from `PENDING_PAYMENT` advances the related `Listing` from `RESERVED` to `SOLD`, the related `Vehicle` from `LISTED` to `SOLD`, the winning `Bid` from `LIVE` to `WON` (or, in the FIXED_PRICE case, the holding `Reservation` from `HOLDING` to `CONVERTED`), every losing live bid from `LIVE` to `LOST` with deposit released, every still-queued reservation to `CANCELLED` with deposit released, and the matching `Warranty` from `PENDING_ACTIVATION` to `ACTIVE`; immediately afterwards the order auto-transitions from `PAID` to `AWAITING_TRANSFER` and the corresponding `TransferCase` is created in `DOCS_PENDING`. A successful DMV transfer (`TransferCase` `IN_PROGRESS` → `SUCCEEDED`) advances the `PurchaseOrder` from `AWAITING_TRANSFER` to `COMPLETED`, advances the `Vehicle` from `SOLD` to `ARCHIVED`, and rewrites `Vehicle.ownership_seller_id` to the buyer's principal id. A rolled-back transfer (`TransferCase` `FAILED` → `ROLLED_BACK`) advances the `PurchaseOrder` from `AWAITING_TRANSFER` to `REFUNDED`, restores the `Listing` from `SOLD` to `ACTIVE`, restores the `Vehicle` from `SOLD` to `LISTED`, voids the `Warranty` (`ACTIVE` → `VOIDED`), and cancels any disbursed `Loan` (`DISBURSED` → `CANCELLED`); `Vehicle.ownership_seller_id` reverts to the original `Seller.id`, and `rolled_back_at` is set to the rollback instant.

### 2.7. Nested Resource Path Validation

URL paths are validated left to right. A request to `/vehicles/{vehicle_id}/assessments` whose `vehicle_id` does not resolve fails with `ERR_NOT_FOUND` and HTTP 404 before any attempt is made to interpret the body; a request to `/listings/{listing_id}/bids` whose listing exists but whose `listing_id` is wrong fails the same way. Body-referenced foreign keys (`vehicle_id`, `listing_id`, `purchase_order_id`, `assessment_report_id`, and so on) are likewise rejected with `ERR_NOT_FOUND` if the referenced row does not exist.

### 2.8. Validation Priority Ordering

When several validations could fire on the same request, they are evaluated in a fixed priority. Authentication runs first: missing headers (`ERR_AUTH_MISSING`) before invalid headers (`ERR_AUTH_INVALID`) before role authorisation (`ERR_FORBIDDEN`). Existence checks run next: path-parameter resolution (`ERR_NOT_FOUND` from path) before body-referenced foreign-key resolution (`ERR_NOT_FOUND` from body). Ownership (`ERR_NOT_OWNER`) is then evaluated, followed by state-machine admissibility (`ERR_INVALID_STATE`). Domain-specific validations follow in this order: the assessment-finalised check (`ERR_ASSESSMENT_NOT_FINALIZED`), then the version-pinning check at approve (`ERR_ASSESSMENT_VERSION_STALE`), then VIN format (`ERR_VIN_INVALID`), then listing-document sufficiency (`ERR_LISTING_DOCS_INSUFFICIENT`), then bid increment (`ERR_BID_TOO_LOW`), then listing-reservability (`ERR_LISTING_NOT_RESERVABLE`), then loan down-payment ratio (`ERR_DOWN_PAYMENT_INSUFFICIENT`), then loan parameter validity (`ERR_LOAN_PARAMS_INVALID`), then deposit limit (`ERR_DEPOSIT_LIMIT_EXCEEDED`), then transfer appointment window (`ERR_APPOINTMENT_OUT_OF_WINDOW`), then warranty activeness (`ERR_WARRANTY_NOT_ACTIVE`), then warranty component coverage (`ERR_COMPONENT_NOT_COVERED`), then transfer-document completeness (`ERR_TRANSFER_DOCS_INCOMPLETE`), then dispute mediation rounds (`ERR_DISPUTE_ROUNDS_EXHAUSTED`), then dispute eligibility (`ERR_DISPUTE_NOT_ELIGIBLE`), then the idempotency replay marker (`ERR_IDEMPOTENCY_REPLAY`), and finally pagination (`ERR_PAGINATION_INVALID`). Earlier-priority failures mask later ones — the response carries only the highest-priority `error_id` that fires.

### 2.9. Precision and Rounding

All monetary fields are stored as integer cents; no fractional cents are ever persisted. Each calculation in §3 is computed in double-precision arithmetic up to its final step, at which point the result is rounded half-up to integer cents. The bid increment, the loan amortisation monthly payment, and the deposit-balance reconciliation use ceiling rounding at the points specified in their narratives — those are the explicit deviations from round-half-up. Mileage is integer kilometres; the discrepancy ratio is compared at full floating-point precision before the boolean flag is set. Assessment scores are integers in the closed range from 0 through 100, also rounded half-up.

### 2.10. Idempotent External Event Processing

External systems (DMV, BANK, INSURANCE, PAYMENT) deliver state-changing notifications via the event-emit capability. Each event carries a `source` (one of `DMV`, `BANK`, `INSURANCE`, `PAYMENT`), an `event_type` string (such as `payment_received`, `transfer_succeeded`, `transfer_failed`, `credit_check_returned`, or `disbursement_completed`), an event-specific `payload` JSON object, and an `idempotency_key` that is unique across the platform's event log. The first arrival is processed normally and persists `processed=true`; any later arrival with the same `idempotency_key` is silently absorbed — the original `ExternalEvent` row is returned, no downstream side-effects fire, the response carries HTTP 200, and the response body's `error_id` is `ERR_IDEMPOTENCY_REPLAY` to mark it as a replay rather than a fresh action. The replay marker is informational, not a rejection.

### 2.11. Concurrency Resolution

Several races between concurrent mutations are resolved deterministically:

1. **Two AUCTION bids of equal amount on the same listing** are serialised on the listing's id; the listing's `active_bid_id` advances monotonically in `amount_cents`. Whichever request commits first wins; the second is rejected with `ERR_BID_TOO_LOW` because a new bid must strictly exceed the current `amount_cents` of the live highest bid plus the applicable increment, and equality is below that threshold.
2. **Two simultaneous first reservations on a FIXED_PRICE listing** are serialised by `Reservation.created_at` (FIFO), with ties broken lexicographically by `Reservation.id`. The earlier one becomes `HOLDING` at `queue_position` 1; the later one becomes `QUEUED` at `queue_position` 2 — both succeed. The `error_id` `ERR_RESERVATION_QUEUED_NOT_HOLDING` (HTTP 409 in catalogue, returned with HTTP 200 in this concurrency mode as an informational marker) is reserved for clients that opt into HOLDING-only mode and see their request placed at a non-1 position.
3. **A delist racing a new reservation** serialises on the listing's `status`. Whichever wins commits; the loser sees `ERR_INVALID_STATE` with HTTP 409.
4. **Two admins racing approve and reject on the same listing under review** likewise serialise on the listing's `status` — the loser receives `ERR_INVALID_STATE`.
5. **A transfer rollback racing a `transfer_succeeded` event** serialises on the transfer case's `status`. If the success event committed first, the rollback is rejected with `ERR_INVALID_STATE` because only `FAILED` is rollback-eligible.
6. **A buyer's bid cancel racing the auction-close timer** serialises on the bid's `status`. If close commits first, the cancel is rejected with `ERR_INVALID_STATE`.
7. **Duplicate external events** with identical `idempotency_key` see the second processed as a no-op, returning the original event and the `ERR_IDEMPOTENCY_REPLAY` marker as described in §2.10.

### 2.12. Audit Logging

Every state transition, ownership change, financial hold, financial release, and external synchronisation produces an `AuditLog` row capturing the acting role (`actor_role`), acting id (`actor_id`, equal to `X-User-ID` of the request that initiated the change, or the literal string `"system"` for automatic transitions driven by the clock or by external events), the affected entity name (`target_entity`), the affected `target_id`, the audit category (`event_type`, one of `STATE_TRANSITION`, `OWNERSHIP_CHANGE`, `FINANCIAL_HOLD`, `FINANCIAL_RELEASE`, `EXTERNAL_SYNC`), the previous value (`from_value`, e.g. the old status, the old `ownership_seller_id`, or the old held-cents balance), the new value (`to_value`), and the timestamp at which the change was committed (`occurred_at`). `AuditLog` rows are immutable and are surfaced through the audit-log list endpoint to platform administrators only.

## 3. Business Logic & Workflows

### 3.1. Party Onboarding, Vehicle Registration, and Assessment

Sellers and buyers are registered by supplying a `legal_name` (the registered legal name of the individual or business), an `id_document_number` (the government-issued identifier or business registration number, which is unique across the platform — duplicates fail at insertion time), and a contact `phone`. A new `Seller` enters with `kyc_status` `PENDING` (which over time may transition to `VERIFIED` or `REJECTED`) and a `total_listings` counter starting at zero. A new `Buyer` enters with `deposit_held_cents` and `deposit_balance_cents` both at zero; the running invariant is that those two fields remain equal at all times (see §3.7).

A `Seller` registers a vehicle by submitting its `vin`, `make`, `model`, `model_year`, `declared_mileage_km`, and `color`. The `vin` must consist of exactly 17 alphanumeric characters with no I, no O, and no Q; any other shape is rejected with `ERR_VIN_INVALID`. The `model_year` must be at least 1980 and at most the current calendar year. The `declared_mileage_km` must be at least 0. The vehicle enters the system in `vehicle_status` `REGISTERED`. Two computed fields, `assessment_score` and `valuation_cents`, both start as null and are filled by the assessment workflow; `verified_mileage_km` is likewise null until the first finalised on-site report. `ownership_seller_id` initially points to the registering seller's id and may later point to a different seller-twin if a sale completes, or revert if a transfer rolls back.

An `Inspector` initiates assessment by creating an `AssessmentReport` against the vehicle. The body carries `vin_history_records` (each item `{date, source, event_type, severity}` where `event_type` is one of `ACCIDENT`, `MAINTENANCE`, `RECALL`, or `REGISTRATION`, and `severity` is one of `NONE`, `MINOR`, or `MAJOR`) and the inspector's identifier (`inspector_user_id`). The report enters in `status` `DRAFT` with `accident_count`, `major_accident_count`, and `maintenance_count` derived directly from the history records, and `provisional_valuation_cents`, `final_valuation_cents`, `mileage_discrepancy_flag`, and `declared_mileage_km` (the report's snapshot field) all initialised to their nulls and zeros.

Requesting on-site inspection advances the report from `DRAFT` to `ONSITE_PENDING`. This requires `vin_history_records` to be non-empty; otherwise the transition is refused with `ERR_INVALID_STATE`. On the `DRAFT → ONSITE_PENDING` step the system computes `provisional_valuation_cents`. Take the base price for the make-model-year (treat the platform-supplied base price as a constant of one million cents per vehicle for the purposes of this calculation), multiply by a mileage factor that is the larger of one half and the value of one minus the declared mileage in kilometres divided by the reference mileage of two hundred thousand kilometres and that ratio further multiplied by the mileage decay constant of one half, and then multiply by a history factor that is one minus the history penalty. The history penalty itself is computed by multiplying the `accident_count` by the per-accident penalty of eight hundred basis points and multiplying the `maintenance_count` by the per-maintenance penalty of fifty basis points, summing the two products, and dividing the sum by ten thousand to convert basis points to a fraction. The product of the base, the mileage factor, and one minus the history penalty is then rounded half-up to integer cents and stored as `provisional_valuation_cents`. This provisional figure is intentionally a coarse estimate — it ignores on-site grades, the major-accident extra penalty, and the discrepancy multiplier.

Finalising on-site inspection advances the report from `ONSITE_PENDING` to `FINALIZED`. The body must carry an `onsite_findings` object with all four sub-grades (`exterior_grade`, `interior_grade`, `mechanical_grade`, each one of `A`, `B`, `C`, or `D`, plus `mileage_km_observed`), and the report's `inspector_user_id` must already be set; either omission rejects with `ERR_INVALID_STATE`. Three calculations fire in sequence on this transition. First, the mileage verification: take the difference between the on-site observed mileage and the snapshot of the seller's declared mileage at the time of finalisation. If the difference is negative — that is, the observed reading is below what was declared — the `mileage_discrepancy_flag` is set to true. If `declared_mileage_km` is greater than zero and the absolute value of the difference divided by the declared mileage is greater than the discrepancy tolerance of five percent, the flag is also set to true. In every other case the flag is false. The system additionally writes the observed mileage to `Vehicle.verified_mileage_km`. Second, the final valuation: take the same one-million-cent base, multiply by a mileage factor computed from the verified mileage in the same shape as the provisional formula (the larger of one half and one minus the verified mileage divided by the reference mileage of two hundred thousand kilometres multiplied by the mileage decay constant of one half), multiply by the average of the three grade values (`A` is one point zero, `B` is zero point nine, `C` is zero point eight, `D` is zero point six — taking the simple arithmetic mean across `exterior_grade`, `interior_grade`, and `mechanical_grade`), then multiply by one minus the history penalty (now `accident_count` times eight hundred basis points plus `major_accident_count` times an extra major-accident penalty of one thousand two hundred basis points plus `maintenance_count` times fifty basis points, all summed and divided by ten thousand), and finally multiply by one minus the discrepancy penalty of fifteen percent if the `mileage_discrepancy_flag` is true (otherwise multiply by one — that is, no further adjustment). Round the result half-up to integer cents and store as `final_valuation_cents`. Third, the assessment score: compute the grade points as the average grade value times one hundred, the mileage points as the larger of zero and one hundred minus the verified mileage divided by the reference mileage of two hundred thousand kilometres further multiplied by one hundred, and the history points as the larger of zero and one hundred minus the `accident_count` times ten minus the `major_accident_count` times fifteen minus an extra deduction of twenty if the `mileage_discrepancy_flag` is true (else zero); combine with weights of zero point five for grades, zero point two for mileage, and zero point three for history, and round the weighted sum half-up to a 0-to-100 integer. Store this on `Vehicle.assessment_score` and store the final valuation on `Vehicle.valuation_cents`.

The first finalised report for a given vehicle advances the vehicle from `REGISTERED` to `ASSESSED`; subsequent finalisations leave the vehicle in `ASSESSED` but refresh `assessment_score`, `valuation_cents`, and `verified_mileage_km`. Whenever a newer report is finalised, every prior report for the same vehicle that was in `FINALIZED` is moved to `SUPERSEDED`.

### 3.2. Listing Creation, Review, and Activation

Once a vehicle has at least one `FINALIZED` `AssessmentReport`, the seller may create a `Listing`. The creation body carries the `vehicle_id`, the `assessment_report_id` to pin to, the `sale_mode` (one of `AUCTION` or `FIXED_PRICE`), the `ask_price_cents` (which is the fixed price in `FIXED_PRICE` mode and the starting price in `AUCTION` mode), the optional `reserve_price_cents` (used only in `AUCTION` mode and required to be null for `FIXED_PRICE`), the `photo_urls` array, and the seller's attestation `documents_authentic_flag`. The pinned report must be `FINALIZED` at creation time and at submit time; otherwise the operation is rejected with `ERR_ASSESSMENT_NOT_FINALIZED`. The pinned report's `vehicle_id` must match the listing's `vehicle_id`. The new listing enters with `status` `DRAFT`, `doc_check_status` `NOT_RUN`, `active_bid_id` and `reservation_buyer_id` both null, and `assessment_report_version` unset (it is filled at submit).

Submitting the listing for review takes it from `DRAFT` to `UNDER_REVIEW`. Three preconditions must hold: the `photo_urls` array must contain at least 6 entries, the `documents_authentic_flag` must be true, and the pinned `AssessmentReport` must still be `FINALIZED`. Photo or attestation insufficiency is rejected with `ERR_LISTING_DOCS_INSUFFICIENT`; an unfinalised pinned report is rejected with `ERR_ASSESSMENT_NOT_FINALIZED`. On success, the listing's `assessment_report_version` is set to the current `version` of the pinned report — this version-pinning becomes the contract that the listing approve step revalidates.

A `PlatformAdmin` then dispositions the under-review listing in one of three ways. Approving advances the listing from `UNDER_REVIEW` to `ACTIVE`, sets `doc_check_status` to `PASS`, and cascades the underlying vehicle from `ASSESSED` to `LISTED`. Approval requires that `doc_check_status` end up as `PASS` and — critically — that the pinned `assessment_report_version` still equal the current version of the pinned `AssessmentReport`; if a newer report has been finalised in the meantime (or any other version-bumping mutation occurred on the pinned report), the approve step is rejected with `ERR_ASSESSMENT_VERSION_STALE`. This is the version-pinning re-validation at approve. Rejecting takes the listing from `UNDER_REVIEW` to `REJECTED` and sets `doc_check_status` to `FAIL`. Returning for revision takes the listing from `UNDER_REVIEW` back to `DRAFT` with no field side-effects beyond the standard `updated_at` and `version` bump, allowing the seller to refresh photos or correct attestations before re-submitting.

Delisting is a seller capability available only when the listing is `ACTIVE` with no in-flight participation: there must be no `Bid` in `LIVE` and no `Reservation` in `HOLDING`. A successful delist transitions the listing from `ACTIVE` to `DELISTED`, cancels any `QUEUED` reservations and releases their deposits, and — if no other listing for the same vehicle is in `UNDER_REVIEW`, `ACTIVE`, or `RESERVED` — cascades the vehicle from `LISTED` back to `ASSESSED`.

### 3.3. Bidding on AUCTION Listings

A `Buyer` participates in an `AUCTION` listing by submitting a `Bid` with the desired `amount_cents`. The bid increment rule is tiered against the current maximum, which is the `amount_cents` of the listing's current `LIVE` bid (read via the listing's `active_bid_id`) if one exists, or the listing's `ask_price_cents` if none has been placed yet. When the current maximum is below the first-tier ceiling of fifty thousand currency units (five million cents), the required increment is five hundred currency units (fifty thousand cents). When the current maximum is at least the first-tier ceiling but below the second-tier ceiling of two hundred thousand currency units (twenty million cents), the required increment is two thousand currency units (two hundred thousand cents). When the current maximum is at least the second-tier ceiling, the required increment is five thousand currency units (five hundred thousand cents). The new bid's `amount_cents` must be at least the current maximum plus the applicable increment; equality at the boundary fails (the required minimum is strictly above the current maximum by the increment). A bid below the required minimum is rejected with `ERR_BID_TOO_LOW`.

A successful bid placement creates a new `Bid` row in `status` `LIVE` with `placed_at` set to the server's current instant, computes its `deposit_cents` as ten percent of the bid amount rounded up to the next whole cent, and acquires the deposit hold against the buyer (`Buyer.deposit_held_cents` increases by the new `deposit_cents`). If a previous `LIVE` bid existed on the same listing, it is moved to `OUTBID` and its deposit hold is released. The listing's `active_bid_id` is updated to the new bid's id. The placement also enforces the deposit limit described in §3.7. The cyclic `LIVE` ↔ `OUTBID` shape is intentional: a buyer who was outbid may place a new bid (new row) and re-acquire the deposit hold; the previously leading buyer is then transitioned `LIVE` → `OUTBID` themselves. Each round of bidding is therefore a new `Bid` row.

A buyer may cancel their own `LIVE` bid before the auction closes; this transitions the bid from `LIVE` to `CANCELLED` and releases the deposit. Cancellation is admissible only when the listing is in `ACTIVE`. If a clock advance has already triggered auction close (concurrent with the cancel attempt), the listing has moved on and the cancel is rejected with `ERR_INVALID_STATE`.

The platform admin or a clock-driven sweep closes the auction. Closing requires choosing the highest `LIVE` bid for the listing; if its `amount_cents` is at least the listing's `reserve_price_cents`, that bid is moved from `LIVE` to `WON`, every other `LIVE` bid for the listing is moved to `LOST` with deposit released, the listing transitions from `ACTIVE` to `RESERVED`, and a `PurchaseOrder` is created in `PENDING_PAYMENT`. If no `LIVE` bid meets the reserve, every `LIVE` bid is moved to `LOST` with deposit released and the listing remains in `ACTIVE` with no `active_bid_id`.

### 3.4. Reservations on FIXED_PRICE Listings

A `Buyer` participates in a `FIXED_PRICE` listing by creating a `Reservation`. The body carries no parameters beyond the path's listing id; the system computes the `deposit_cents` for every reservation on that listing as five percent of the listing's `ask_price_cents` rounded up to the next whole cent. Reservations cannot be created when the listing's status is anything other than `ACTIVE` or `RESERVED`; otherwise the creation is rejected with `ERR_LISTING_NOT_RESERVABLE`. Reservations are placed at the next available `queue_position`, which is the count of non-terminal reservations on the listing plus one. Reservations enter in `status` `QUEUED`, with `hold_expires_at` null while they are at any position other than 1.

Promotion to position 1 (either at creation when the queue is empty, or when the previous position-1 holder expires or cancels) advances the reservation from `QUEUED` to `HOLDING`. Promotion sets `hold_expires_at` to twenty-four hours from the moment of promotion, acquires the buyer's deposit hold (`Buyer.deposit_held_cents` increases by the reservation's `deposit_cents`), and — if the listing was in `ACTIVE` — advances the listing from `ACTIVE` to `RESERVED`. The `reservation_buyer_id` field on the listing is set to the buyer's id of the holder.

Conversion is the happy path: while in `HOLDING`, the buyer creates and pays for a `PurchaseOrder`. Successful payment advances the reservation from `HOLDING` to `CONVERTED` (along with all the listing/vehicle/warranty cascades described in §2.6 and §3.5), and every still-queued reservation on the same listing is moved to `CANCELLED` with its deposit released.

If the holder does not pay before `hold_expires_at`, a clock advance past that instant moves the reservation from `HOLDING` to `EXPIRED`. The deposit is released. If a next-position reservation exists on the same listing, that next reservation is promoted from `QUEUED` to `HOLDING`. If none exists, the listing is restored from `RESERVED` to `ACTIVE`.

A buyer may cancel their reservation at any time. Cancelling a `QUEUED` reservation transitions `QUEUED` to `CANCELLED` with no deposit movement (none was held). Cancelling a `HOLDING` reservation transitions `HOLDING` to `CANCELLED`, releases the deposit, and either promotes the next-position reservation (advancing the next `QUEUED` to `HOLDING`) or — if none exists — restores the listing from `RESERVED` back to `ACTIVE`. Concurrency between a delist and a fresh reservation is resolved as described in §2.11; the loser sees `ERR_INVALID_STATE`.

### 3.5. Purchase Order, Payment, and Vehicle Sale

A `Buyer` who has either won an auction or holds a `HOLDING` reservation creates a `PurchaseOrder` against the listing. The body carries the `listing_id` and the `payment_method`, which is `FULL_PAYMENT` by default and may be set to `LOAN`. On creation the system snapshots the listing's `vehicle_id` and `seller_id` onto the order's `vehicle_id` and `seller_id`, sets the `agreed_price_cents` to the winning `Bid.amount_cents` (for auctions) or to the `ask_price_cents` (for fixed-price reservations), sets the `buyer_id` to the acting buyer, and persists the order in `status` `PENDING_PAYMENT`. For `FULL_PAYMENT`, `down_payment_cents` equals `agreed_price_cents` and `loan_id` remains null. For `LOAN`, both `down_payment_cents` and `loan_id` are filled when the loan is approved (see §3.6).

A buyer may cancel an order before payment by transitioning the order from `PENDING_PAYMENT` to `CANCELLED`. Cancellation releases any held bid or reservation deposit, restores the listing from `RESERVED` back to `ACTIVE`, and cascades any associated loan to `CANCELLED`.

Payment arrives as an external `payment_received` event referencing the order. On success — and provided the order is in `PENDING_PAYMENT`, and provided that, when the order's `payment_method` is `LOAN`, the linked `Loan` is in `DISBURSED` — the order is moved to `PAID` and `paid_at` is set to the event's processed instant. The `PAID` step fires a fan-out: the listing transitions from `RESERVED` to `SOLD`; the vehicle transitions from `LISTED` to `SOLD`; for an auction, the winning bid is moved from `LIVE` to `WON` while every other `LIVE` bid is moved to `LOST` with deposit released; for a fixed-price reservation, the holding reservation is moved from `HOLDING` to `CONVERTED` while every still-queued reservation is moved to `CANCELLED` with deposit released; the matching `Warranty` is activated by moving from `PENDING_ACTIVATION` to `ACTIVE`, with `effective_at` set to the order's `paid_at` and `expires_at` computed per §3.8. All other still-active or under-review listings for the same vehicle (in `DRAFT`, `UNDER_REVIEW`, `ACTIVE`, or `RESERVED`) are moved to `DELISTED`. Once these side-effects have completed, the order auto-transitions from `PAID` to `AWAITING_TRANSFER`, and a new `TransferCase` is created in `DOCS_PENDING` with the required-document checklist seeded (see §3.7). This two-step `PAID` → `AWAITING_TRANSFER` is intentional: external observers should be able to see the order pass through `PAID` between activation and transfer creation.

### 3.6. Financing via Loan Application

Buyers who select `payment_method` `LOAN` apply against an existing `PurchaseOrder` by creating a `Loan` carrying the `lender_code` (one of `LENDER_A`, `LENDER_B`, or `LENDER_C`), the `requested_principal_cents`, the `down_payment_ratio_bp` (basis points where 2000 means twenty percent), and the `term_months` (one of 12, 24, 36, 48, 60, or 72). The `down_payment_ratio_bp` must be at least the lender's minimum: `LENDER_A` requires at least 1500 basis points, `LENDER_B` at least 2000 basis points, `LENDER_C` at least 2500 basis points; any value below — even by a single basis point — fails with `ERR_DOWN_PAYMENT_INSUFFICIENT`. The boundary case of exactly the lender minimum must succeed. The `term_months` must be one of the six allowed values; the `requested_principal_cents` must be greater than zero and must not exceed the order's `agreed_price_cents` minus the down-payment computed at the lender's minimum ratio. Any of those parameter violations is rejected with `ERR_LOAN_PARAMS_INVALID`. The loan enters in `status` `APPLIED` with `approved_principal_cents`, `monthly_payment_cents`, `total_interest_cents`, `credit_score`, and `disbursed_at` all initialised to nulls.

A platform admin runs the credit check, advancing the loan from `APPLIED` to `CREDIT_CHECKING`. A buyer may also cancel before this step, taking the loan from `APPLIED` directly to `CANCELLED`.

The bank returns the credit score asynchronously as a `credit_check_returned` event. If the buyer's `credit_score` meets the lender's minimum (`LENDER_A` requires at least 680, `LENDER_B` at least 640, `LENDER_C` at least 600) and the down-payment ratio is at or above the lender's minimum, the loan transitions from `CREDIT_CHECKING` to `APPROVED`. On approval the system computes the amortisation in a pinned five-step order. First, the lender APR in basis points is determined from the lender code and the credit score: `LENDER_A` charges 480 basis points if the score is at least 740, otherwise 580 basis points if the score is at least 680, otherwise rejection; `LENDER_B` charges 580 basis points if the score is at least 700, otherwise 680 basis points if the score is at least 640, otherwise rejection; `LENDER_C` charges 780 basis points if the score is at least 660, otherwise 880 basis points if the score is at least 600, otherwise rejection. Second, the maximum principal is computed as the order's `agreed_price_cents` minus the down-payment requirement, where the down-payment requirement is the order's `agreed_price_cents` multiplied by the buyer's `down_payment_ratio_bp` divided by ten thousand and rounded up to the next whole cent. Third, the `approved_principal_cents` is the smaller of the buyer's `requested_principal_cents` and the maximum principal just computed. Fourth, the `monthly_payment_cents` is the standard amortisation: take the lender APR in basis points divided by ten thousand divided by twelve to get the monthly rate, then take the `approved_principal_cents` multiplied by the monthly rate divided by one minus the quantity (one plus the monthly rate) raised to the negative of the `term_months`, and round the whole thing up to the next whole cent (single ceiling at the end). Fifth, the `total_interest_cents` is the `monthly_payment_cents` multiplied by the `term_months` minus the `approved_principal_cents` (no further rounding). If the credit score is insufficient or the down-payment ratio fails, the loan transitions from `CREDIT_CHECKING` to `REJECTED` with `approved_principal_cents` set to zero.

The bank then disburses asynchronously as a `disbursement_completed` event, advancing the loan from `APPROVED` to `DISBURSED` and setting `disbursed_at` to the event instant. A loan in `APPROVED` may be cancelled if the underlying purchase order is cancelled before disbursement (`APPROVED` → `CANCELLED`). A loan in `DISBURSED` is moved to `CANCELLED` only if the purchase order is later refunded via transfer rollback — this represents the bank's claim against the lender and is recorded in audit but not unwound on the buyer's side automatically.

### 3.7. Ownership Transfer at the DMV

The `PAID` cascade creates a `TransferCase` in `status` `DOCS_PENDING` with a seeded `required_documents` checklist. Each item in the checklist is `{doc_type, submitted, doc_url}` with `doc_type` drawn from `ID_BUYER`, `ID_SELLER`, `TITLE`, `REGISTRATION`, `RELEASE_OF_LIEN`, and `EMISSIONS_CERT`; every item starts with `submitted` false and `doc_url` null. The case also exposes `appointment_at` (initially null), `dmv_office_code` (null), `license_plate_action` defaulting to `REASSIGN`, `new_plate_number` (null), `failure_reason` (null), and `rolled_back_at` (null).

Either party — buyer or seller — uploads a document by submitting `doc_type` and `doc_url`; the matching checklist item is marked `submitted` true with the supplied URL. Once every item has `submitted` true, the buyer may book a DMV appointment by supplying the `appointment_at` timestamp, the `dmv_office_code`, and the `license_plate_action` (one of `KEEP_OLD`, `REASSIGN`, or `NEW_NUMBER`); when the action is `NEW_NUMBER`, the `new_plate_number` must be a non-empty string, and when the action is anything else, `new_plate_number` must remain null. Document or plate-rule violations are rejected with `ERR_TRANSFER_DOCS_INCOMPLETE`. The `appointment_at` must be strictly later than the current instant, and the gap from now to `appointment_at` must be at most sixty days; otherwise the booking is rejected with `ERR_APPOINTMENT_OUT_OF_WINDOW`. A successful booking transitions the case from `DOCS_PENDING` to `APPOINTMENT_BOOKED`.

When the platform clock advances past `appointment_at`, the case auto-transitions from `APPOINTMENT_BOOKED` to `IN_PROGRESS`. From there, the DMV's outcome arrives as one of two external events. A `transfer_succeeded` event advances the case from `IN_PROGRESS` to `SUCCEEDED`, advances the order from `AWAITING_TRANSFER` to `COMPLETED`, advances the vehicle from `SOLD` to `ARCHIVED`, and rewrites `Vehicle.ownership_seller_id` to the buyer's principal id (recorded as an `OWNERSHIP_CHANGE` audit entry). A `transfer_failed` event advances the case from `IN_PROGRESS` to `FAILED` and writes the event payload's reason to `failure_reason`. A platform admin then explicitly invokes rollback on a failed case, advancing the case from `FAILED` to `ROLLED_BACK` with `rolled_back_at` set to the rollback instant; this triggers the full compensation cascade described in §2.6 — the order is moved from `AWAITING_TRANSFER` to `REFUNDED`, the listing is restored from `SOLD` to `ACTIVE`, the vehicle from `SOLD` to `LISTED`, the warranty from `ACTIVE` to `VOIDED`, any disbursed loan from `DISBURSED` to `CANCELLED`, and `Vehicle.ownership_seller_id` reverts to the original seller's id. Rollback is admissible only on `FAILED` cases; attempting it on any other status is rejected with `ERR_INVALID_STATE`. The race between rollback and a `transfer_succeeded` event is resolved per §2.11 — if success commits first, rollback fails because the case is no longer rollback-eligible.

A platform-wide cap protects the buyer from accidental over-commitment of capital. Each buyer's `deposit_held_cents` (the running sum across all of their `LIVE` bids and their `HOLDING` reservation, which by invariant equals the buyer's `deposit_balance_cents`) must not exceed fifty million cents. A new bid or reservation that would push the total above this limit is rejected with `ERR_DEPOSIT_LIMIT_EXCEEDED` on placement. The deposit reconciliation is recomputed on every bid or reservation status change as the sum of `deposit_cents` over the buyer's `LIVE` bids plus the sum over the buyer's `HOLDING` reservations; this recomputation is order-independent (it is a sum) but, when iteration order matters for audit replay, the buyer-scoped FIFO order by `created_at` is the canonical order. The two computed fields `deposit_held_cents` and `deposit_balance_cents` must remain equal at all times.

### 3.8. Warranty Activation, Coverage, and Claims

Every `PurchaseOrder` gives rise to a `Warranty` whose `package_code` is supplied by the buyer at order time and is one of `BASIC`, `STANDARD`, or `PREMIUM`. The warranty enters in `status` `PENDING_ACTIVATION`, with `effective_at` and `expires_at` both null and `claims_count` and `total_claim_payout_cents` both zero. The package code determines the `coverage_scope`: `BASIC` covers `[POWERTRAIN]`, `STANDARD` covers `[POWERTRAIN, ELECTRICAL, COOLING]`, and `PREMIUM` covers `[POWERTRAIN, ELECTRICAL, COOLING, INFOTAINMENT, SUSPENSION, INTERIOR]`. Activation fires as part of the order's `PAID` cascade: the warranty moves from `PENDING_ACTIVATION` to `ACTIVE`, `effective_at` is set to the order's `paid_at`, and `expires_at` is computed by adding the package duration in calendar months — `BASIC` adds six months, `STANDARD` adds twelve months, `PREMIUM` adds twenty-four months — using end-of-month clamp behaviour (an `effective_at` of January 31 plus one month resolves to February 28 or February 29 depending on the year). When the platform clock advances past `expires_at`, the warranty transitions from `ACTIVE` to `EXPIRED`. A transfer rollback that refunds the order, or a dispute that resolves as `REFUND_FULL`, voids the warranty by transitioning it from `ACTIVE` to `VOIDED`.

A buyer files a claim against an `ACTIVE` warranty (the path's `warranty_id` identifies the parent warranty, and the new claim's `warranty_id` is set to that value) by submitting the `component` (which must be in `coverage_scope` — otherwise `ERR_COMPONENT_NOT_COVERED`) and the `claimed_amount_cents`. The claim is admissible only while the warranty is `ACTIVE` and the current instant is strictly before `expires_at`; otherwise `ERR_WARRANTY_NOT_ACTIVE` fires. A new claim enters in `status` `PENDING`. A platform admin approves the claim, advancing it from `PENDING` to `APPROVED` with the `approved_amount_cents` computed as the smallest of (a) the buyer's `claimed_amount_cents`, (b) the per-claim cap of two hundred thousand cents for `BASIC`, five hundred thousand cents for `STANDARD`, or one million five hundred thousand cents for `PREMIUM`, and (c) the remaining headroom under the package's total cap, where the total cap is five hundred thousand cents for `BASIC`, two million cents for `STANDARD`, and six million cents for `PREMIUM`, and the headroom is the larger of zero and the total cap minus the warranty's running `total_claim_payout_cents`. A platform admin may instead reject the claim, advancing it from `PENDING` to `REJECTED`. Approved claims are settled by an external payment event from the insurance system, advancing the claim from `APPROVED` to `PAID`; on settlement the warranty's `claims_count` is incremented and `total_claim_payout_cents` is recomputed by summing the `approved_amount_cents` of the warranty's settled claims.

### 3.9. Dispute Mediation and Resolution

A buyer or seller may file a `DisputeCase` against a `PurchaseOrder`, but only when the order's status is `COMPLETED` or `AWAITING_TRANSFER`; filing against a pre-payment order is rejected with `ERR_DISPUTE_NOT_ELIGIBLE`. The body carries the `complainant_role` (`BUYER` or `SELLER`), the free-text `complaint_text`, and an optional list of `evidence_items`, each item shaped as `{url, kind}` where `kind` is one of `PHOTO`, `VIDEO`, `DOC`, or `MESSAGE_LOG`. The case enters in `stage` `SUBMITTED` with `round_count` zero, `third_party_report_url` null, `resolution` null, and `refund_amount_cents` null.

Mediation is multi-stage. A platform admin starts review by transitioning the case from `SUBMITTED` to `EVIDENCE_REVIEW`, which increments `round_count` by one. From `EVIDENCE_REVIEW` the admin has three exits. They may request more evidence, transitioning back to `SUBMITTED` for another round; this cyclic shape is capped — `round_count` may not exceed the maximum mediation rounds of three, and any start-review or request-more-evidence step that would push it beyond is rejected with `ERR_DISPUTE_ROUNDS_EXHAUSTED`. They may request a third-party inspection, transitioning from `EVIDENCE_REVIEW` to `THIRD_PARTY_INSPECTION`; once the inspection report arrives (carried as `third_party_report_url` in the submit step), the case transitions from `THIRD_PARTY_INSPECTION` to `RESOLUTION_PROPOSED` provided the URL is non-empty. They may also skip the third-party path entirely by proposing a resolution directly, taking the case from `EVIDENCE_REVIEW` to `RESOLUTION_PROPOSED` with the `resolution` set in the request body to one of `REFUND_FULL`, `REFUND_PARTIAL`, `COMPENSATE_SELLER`, or `NO_ACTION`.

Executing the proposed resolution advances the case from `RESOLUTION_PROPOSED` to `CLOSED` and computes `refund_amount_cents`. If the resolution is `REFUND_FULL`, `refund_amount_cents` equals the order's `agreed_price_cents`, and the order is cascaded into `REFUNDED` with the full transfer-rollback compensation chain (listing, vehicle, warranty, loan all reverted as in §2.6) and the warranty is moved from `ACTIVE` to `VOIDED`. If the resolution is `REFUND_PARTIAL`, the refund is computed as the order's `agreed_price_cents` multiplied by a base percentage and rounded half-up to integer cents, where the base percentage is ten percent if no `third_party_report_url` was filed and thirty percent if one was; an additional ten percentage points are added to the base if the latest `AssessmentReport` for the vehicle had its `mileage_discrepancy_flag` set to true at sale time. The vehicle, listing, and warranty are not touched in `REFUND_PARTIAL`. If the resolution is `COMPENSATE_SELLER`, the buyer pays the seller five percent of the order's `agreed_price_cents` rounded half-up — this is a refund-from-buyer accounting movement, not a return of the vehicle. If the resolution is `NO_ACTION`, `refund_amount_cents` is zero and no monetary movement occurs. A dispute that the admin starts but does not yet have an executable resolution must have its `resolution` set before the execute step; otherwise execute is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications to existing resources are returned with HTTP 200. Read endpoints return 200. The auth, existence, and authorisation rules in §2.1 and §2.7 apply uniformly across the table; per-endpoint behaviours, request and response bodies, and side-effects are described in §3 and §2. The full inventory:

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|---------------------|
| POST   | `/sellers` | Register a seller | `PlatformAdmin`, `Seller` |
| POST   | `/buyers` | Register a buyer | `PlatformAdmin`, `Buyer` |
| GET    | `/buyers/{id}` | Read buyer (deposit balance reflects current holds) | `PlatformAdmin`, `Buyer` |
| POST   | `/vehicles` | Register a vehicle | `Seller` |
| GET    | `/vehicles/{id}` | Read vehicle | `PlatformAdmin`, `Seller`, `Buyer`, `Inspector` |
| GET    | `/vehicles` | List vehicles (filter by status, seller_id) | `PlatformAdmin`, `Seller`, `Buyer` |
| POST   | `/vehicles/{id}/assessments` | Create an assessment report for a vehicle | `Inspector` |
| POST   | `/assessments/{id}/request-onsite` | Move a draft report to on-site pending; computes provisional valuation | `Inspector` |
| POST   | `/assessments/{id}/finalize` | Submit on-site findings; finalises the report | `Inspector` |
| GET    | `/assessments/{id}` | Read an assessment report | `PlatformAdmin`, `Seller`, `Buyer`, `Inspector` |
| POST   | `/listings` | Create a listing pinned to a finalised assessment | `Seller` |
| POST   | `/listings/{id}/submit` | Submit listing for admin review | `Seller` |
| POST   | `/listings/{id}/approve` | Approve under-review listing; cascade vehicle to listed | `PlatformAdmin` |
| POST   | `/listings/{id}/reject` | Reject under-review listing | `PlatformAdmin` |
| POST   | `/listings/{id}/return-for-revision` | Return under-review listing to draft for the seller | `PlatformAdmin` |
| POST   | `/listings/{id}/delist` | Seller delists an active listing | `Seller` |
| GET    | `/listings` | List listings with filters | `PlatformAdmin`, `Seller`, `Buyer` |
| GET    | `/listings/{id}` | Read a listing | `PlatformAdmin`, `Seller`, `Buyer` |
| POST   | `/listings/{id}/bids` | Place a bid on an auction listing | `Buyer` |
| POST   | `/listings/{id}/close-auction` | Close an active auction | `PlatformAdmin` |
| POST   | `/bids/{id}/cancel` | Buyer cancels their live bid | `Buyer` |
| GET    | `/listings/{id}/bids` | List bids on a listing | `PlatformAdmin`, `Seller`, `Buyer` |
| POST   | `/listings/{id}/reservations` | Reserve a fixed-price listing | `Buyer` |
| POST   | `/reservations/{id}/cancel` | Buyer cancels their reservation | `Buyer` |
| GET    | `/listings/{id}/reservations` | List reservations on a listing | `PlatformAdmin`, `Seller`, `Buyer` |
| POST   | `/purchase-orders` | Create a purchase order from a winning bid or holding reservation | `Buyer` |
| GET    | `/purchase-orders/{id}` | Read a purchase order | `PlatformAdmin`, `Seller`, `Buyer` |
| POST   | `/purchase-orders/{id}/cancel` | Buyer cancels a pending order before payment | `Buyer` |
| POST   | `/purchase-orders/{id}/loans` | Apply for a loan against a purchase order | `Buyer` |
| POST   | `/loans/{id}/run-credit-check` | Admin moves a loan into credit-checking | `PlatformAdmin` |
| POST   | `/loans/{id}/cancel` | Cancel a loan in applied or approved state | `Buyer` |
| GET    | `/loans/{id}` | Read a loan | `PlatformAdmin`, `Buyer` |
| GET    | `/transfers/{id}` | Read a transfer case | `PlatformAdmin`, `Seller`, `Buyer` |
| PATCH  | `/transfers/{id}/documents` | Upload or mark a checklist document submitted | `Buyer`, `Seller` |
| POST   | `/transfers/{id}/book-appointment` | Book the DMV appointment | `Buyer` |
| POST   | `/transfers/{id}/rollback` | Roll back a failed transfer; cascades full compensation | `PlatformAdmin` |
| GET    | `/warranties/{id}` | Read a warranty | `PlatformAdmin`, `Buyer`, `Seller` |
| POST   | `/warranties/{id}/claims` | File a warranty claim | `Buyer` |
| POST   | `/warranty-claims/{id}/approve` | Approve a pending claim; computes approved amount | `PlatformAdmin` |
| POST   | `/warranty-claims/{id}/reject` | Reject a pending claim | `PlatformAdmin` |
| POST   | `/purchase-orders/{id}/disputes` | File a dispute on a completed or awaiting-transfer order | `Buyer`, `Seller` |
| POST   | `/disputes/{id}/start-review` | Move dispute to evidence review (round_count++) | `PlatformAdmin` |
| POST   | `/disputes/{id}/request-more-evidence` | Cycle back to submitted for another round | `PlatformAdmin` |
| POST   | `/disputes/{id}/request-third-party` | Move into third-party inspection | `PlatformAdmin` |
| POST   | `/disputes/{id}/submit-third-party-report` | Record the third-party report URL | `PlatformAdmin` |
| POST   | `/disputes/{id}/propose-resolution` | Propose a resolution skipping third-party | `PlatformAdmin` |
| POST   | `/disputes/{id}/execute` | Execute the proposed resolution; computes refund | `PlatformAdmin` |
| POST   | `/_events/emit` | Emit an external event (DMV, BANK, INSURANCE, PAYMENT) | `PlatformAdmin` |
| POST   | `/_clock/advance` | Advance the virtual clock to a supplied `to_iso_8601` instant | `PlatformAdmin` |
| GET    | `/audit-logs` | List audit log entries with filters `target_entity`, `target_id`, `event_type` | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status |
|----------|-------------|
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_INVALID` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VIN_INVALID` | 422 |
| `ERR_ASSESSMENT_NOT_FINALIZED` | 422 |
| `ERR_ASSESSMENT_VERSION_STALE` | 409 |
| `ERR_LISTING_DOCS_INSUFFICIENT` | 422 |
| `ERR_BID_TOO_LOW` | 422 |
| `ERR_LISTING_NOT_RESERVABLE` | 409 |
| `ERR_RESERVATION_QUEUED_NOT_HOLDING` | 409 |
| `ERR_DEPOSIT_LIMIT_EXCEEDED` | 422 |
| `ERR_DOWN_PAYMENT_INSUFFICIENT` | 422 |
| `ERR_LOAN_PARAMS_INVALID` | 422 |
| `ERR_APPOINTMENT_OUT_OF_WINDOW` | 422 |
| `ERR_TRANSFER_DOCS_INCOMPLETE` | 422 |
| `ERR_WARRANTY_NOT_ACTIVE` | 409 |
| `ERR_COMPONENT_NOT_COVERED` | 422 |
| `ERR_DISPUTE_ROUNDS_EXHAUSTED` | 409 |
| `ERR_DISPUTE_NOT_ELIGIBLE` | 422 |
| `ERR_IDEMPOTENCY_REPLAY` | 200 |
| `ERR_PAGINATION_INVALID` | 400 |
| `ERR_VERSION_CONFLICT` | 409 |
