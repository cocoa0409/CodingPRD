# Consignment Thrift Resale API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Consignment & Thrift Clothing Resale API, the back-office platform that runs a consignment storefront end to end. A consignment store does not own the garments it sells; it takes goods on behalf of individual sellers — the **consignors** — grades and prices them, places them on the floor, and shares the proceeds when they sell. The platform must therefore track, for every garment, both its physical journey through intake and the financial obligation it represents to the person who brought it in.

The system is built around three intertwined disciplines. The first is **pricing**: each garment carries an original list price set at grading, and an automatic markdown schedule steadily discounts it as it ages on the floor, never dropping below a configured floor. The second is the **split economics** of consignment: when an item sells, the proceeds are divided between the consignor and the store according to the terms pinned on the consignor's agreement, with two distinct calculation bases and two distinct payout channels (cash or store credit). The third is **settlement and audit**: cash owed to consignors accrues in a ledger, is swept once per business day into an immutable daily settlement, and every reversal (a voided sale, a counterfeit verdict) must leave the books exactly where they started. Because graders, authenticators, cashiers, and settlement managers each touch the same garment at different stages — and because an authenticator must never be allowed to rubber-stamp goods they themselves graded — the platform enforces a strict separation of duties throughout.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request, except for the public registration of a consignor and unauthenticated public reads, must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header on a protected endpoint is rejected with `ERR_UNAUTHENTICATED`; a request whose `X-User-Role` header is present but holds a value that is not one of the five recognized roles is likewise rejected with `ERR_UNAUTHENTICATED` (the unrecognized role is treated as a failed authentication, not as a forbidden role). When the headers are present and the role is one of the five recognized roles but is not permitted to perform the requested operation per the matrix in Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `StoreAdmin`, `IntakeGrader`, `Authenticator`, `CashierClerk`, and `SettlementManager`. `StoreAdmin` owns configuration — registering consignors, creating markdown schedules and agreements, and driving the test clock — and holds broad administrative read access. `IntakeGrader` grades incoming garments and manages the floor lifecycle. `Authenticator` examines branded or luxury goods. `CashierClerk` rings and voids sales and redeems store credit at the till. `SettlementManager` runs the daily settlement, disputes authentications, and disposes of unsold stock.

All five roles use an **opaque** operator identity. When `X-User-Role` is any of `StoreAdmin`, `IntakeGrader`, `Authenticator`, `CashierClerk`, or `SettlementManager`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The server may nonetheless record it where a state transition writes it — for example, an `IntakeGrader`'s identifier is stamped onto `graded_by_user_id` on the `Item` they accept or reject, an `Authenticator`'s identifier onto `opened_by_user_id` on the `AuthenticationReview` they open, and a `CashierClerk`'s identifier onto `rung_by_user_id` on the `Sale` they ring. These recorded identifiers exist to enforce the separation-of-duties rule (see Section 3) and are never treated as ownership keys.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10 when omitted, may be no less than 1, and no greater than 100. The `offset` parameter is the number of records to skip from the start of the result set and defaults to 0. A `limit` or `offset` value outside its permitted bounds is rejected with `ERR_VALIDATION_PAGINATION`.

Unless a specific endpoint states otherwise, list results are ordered by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, with `has_more` true exactly when `offset` plus the number of records in the returned window is less than `total_count`. Query-parameter filters on list endpoints (such as `status`, `listing_status`, `grading_status`, `disposition`, `consignor_id`, or `settlement_id`) are matched by exact string equality and are never themselves validated against an enumerated set: a filter value that matches no record — including a syntactically valid but unknown enum value — simply yields an empty result set rather than an `ERR_INVALID_REQUEST`.

Across every creating or modifying operation, the server first checks that the request body is well-formed before it applies any business rule: required fields must be present, every value must be of the expected type, each enumerated field must hold one of its allowed values, a `list_price_cents` must be at least 0, a `split_pct` must fall strictly between 0 and 1, and an `email` must be a syntactically valid address. A request that omits a required field, carries a malformed type, or supplies an out-of-range scalar is rejected with `ERR_INVALID_REQUEST`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system are addressable, mutable entities that carry a standard quartet of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, also with three fractional digits, refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on each mutation of the resource. These four fields are present on `Consignor`, `MarkdownSchedule`, `ConsignorAgreement`, `IntakeBatch`, `Item`, `AuthenticationReview`, `Sale`, `DailySettlement`, and `DonationRecord`.

Three entities are append-only ledger records rather than mutable resources and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version`. These are the `SaleLine` (a child line of a `Sale`), the `PayoutLedgerEntry`, and the `StoreCreditTransaction`. A `SaleLine` is never independently mutated; the only way its enclosing data changes is through the void of its parent `Sale`, which flips other records rather than editing the line in place. Likewise, a sale void does not edit a `PayoutLedgerEntry` or a `StoreCreditTransaction` after the fact — it appends a compensating record or flips a status field, as described in Section 3.

### 2.5. Nested Resource Retrieval and Reference Resolution

Several endpoints address a resource nested under, or filtered by, a parent — for example, the reviews belonging to an item, or the ledger entries belonging to a consignor. When a path contains more than one resource identifier, the server validates them left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing row. A single path identifier that does not exist likewise yields `ERR_NOT_FOUND`.

References supplied in a request body are resolved separately. When a creation payload names a foreign resource — a `consignor_id`, an `agreement_id`, a `batch_id`, an `item_id`, or a `markdown_schedule_id` — and that identifier does not resolve to an existing row, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. This body-reference check applies to creating an agreement, opening an intake batch, adding an item, ringing a sale, and opening an authentication review.

When several checks could apply to one request, they are evaluated in a fixed precedence so that the failure surfaced is always the earliest applicable one. Authentication of the headers comes first, then the role-permission check, then the existence of any path-referenced resource, then the resolution of any body foreign-key reference, then the check that the target resource is in a state from which the requested transition is defined, then the optimistic-concurrency version check on endpoints that take one, and only after all of those do the operation-specific business rules (separation of duties, authentication gating, on-floor and pricing constraints, window timing, uniqueness, and fiscal limits) run. Thus a missing header is reported as `ERR_UNAUTHENTICATED` before any role or existence concern, a forbidden role as `ERR_FORBIDDEN_ROLE` before existence, and a state violation (`ERR_INVALID_STATE`) before the stale-version check — never the reverse.

### 2.6. Monetary Precision and Rounding

Every monetary quantity in the system is stored and returned as an integer number of cents. Where a calculation produces a fractional cent, the result is rounded **half up** to the nearest whole cent unless a specific rule states that it is floored instead. The markdown floor price and the donation tax-receipt valuation are computed by **flooring** to a whole cent (truncating any fraction toward zero); the markdown raw price, the consignor proceeds, and the store-credit bonus are computed by **rounding half up**. Section 3 states, for each calculation, which rule applies and in what order operations are performed; the ordering is significant because the platform deliberately rounds each sale line independently and then sums the already-rounded integers when rolling a settlement up, rather than summing first and rounding once.

### 2.7. Derived Balance Reconciliation

Several fields are never written directly by a client; they are **derived** by reconciling the underlying ledgers, and they are recomputed whenever the records that feed them change and whenever the owning resource is read. A consignor's `store_credit_cents` is the sum of the `amount_cents` of all that consignor's `StoreCreditTransaction` records whose `status` is `POSTED`; voided transactions are excluded. It may never be negative. A consignor's `unsettled_payable_cents` is the sum of the `amount_cents` of that consignor's `PayoutLedgerEntry` records that have no `settlement_id` yet and whose `entry_type` is either `SALE_PAYOUT` or `REVERSAL`; it represents the cash still owed for sold items not yet swept into a finalized settlement, and it may be negative if reversals have outrun accrued payouts. A consignor's `lifetime_payout_cents` is the sum of the `amount_cents` of that consignor's `PayoutLedgerEntry` records that already carry a `settlement_id` and whose `entry_type` is `SALE_PAYOUT`; it is the cash actually paid out across all finalized settlements and is never negative. An `IntakeBatch`'s `item_count` is the derived count of `Item` records whose `batch_id` equals that batch. Reading a consignor recomputes all three of its balances before returning; reading a batch recomputes its `item_count` before returning.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of the resource by submitting that resource's last observed `version`, and they reject the write if the stored `version` has moved on. These are the only two endpoints that take a version field; no other endpoint accepts or requires one.

Grading an item requires the request to carry `expected_item_version`, which must equal the target `Item`'s current `version`. If another writer has advanced the item's `version` since the client last read it, the grade is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412). This matters because a `COUNTERFEIT` authentication verdict may have already cascaded a `REJECTED` grading status onto the item and bumped its `version`; without the check, a grader holding a stale view would silently overwrite that verdict-driven rejection.

Finalizing a settlement requires the request to carry `expected_settlement_version`, which must equal the target `DailySettlement`'s current `version`. If the settlement's `version` has advanced since the client last read it, the finalize is rejected with `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412). A settlement's `version` can advance not only through its own transitions but also when a late same-day sale is voided and the reversal touches the settlement's pending scope; a client carrying an older `version` is holding a stale view and must re-read before sweeping payouts.

### 2.9. Hierarchical Consistency and Cascades

Many operations in this domain mutate more than one resource. When an operation changes a state on one entity that another entity's state depends on, the server propagates the change immediately and independently: each affected resource has its own `updated_at` refreshed and its own `version` incremented as part of the same operation. A sale ringing a garment, for instance, does not merely mark the `Item` as sold — it creates a `SaleLine`, writes a payout or store-credit record, and recomputes the consignor's derived balances, all within the one operation. An authentication verdict of `COUNTERFEIT` does not merely close the review — it also stamps the item's authentication outcome and cascades a rejection onto the item's grading status. Section 3 describes each cascade where the workflow that triggers it lives; the governing principle is that the books and the lifecycle states are always left mutually consistent at the end of every operation, with no deferred reconciliation.

### 2.10. The Aging Clock

Markdown pricing and the unsold-disposition return window are both driven by the passage of time measured against a server-held logical clock. The platform exposes an administrative test-driving capability that sets the server's current UTC instant to a supplied value, named `to_iso8601` in the request, so that aging and date math can be exercised deterministically. All age and calendar-date computations performed by subsequent requests use the clock's current instant as "now." This capability is restricted to `StoreAdmin`.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Consignor and Their Terms

The relationship begins when a `StoreAdmin` registers a **consignor** by supplying a `full_name`, which must be non-empty, and an `email`, which must be non-empty and unique across all consignors. A duplicate email is rejected with `ERR_DUPLICATE_EMAIL`. A freshly registered consignor starts in `ACTIVE` status, with `store_credit_cents`, `unsettled_payable_cents`, and `lifetime_payout_cents` all initialized to zero. A consignor's `status` is one of `ACTIVE`, `SUSPENDED`, or `CLOSED`, and a `StoreAdmin` may move it among those values to suspend, close, or reactivate the account.

Before any goods can change hands, a `StoreAdmin` must publish at least one **markdown schedule** and bind it into a **consignor agreement**. A markdown schedule is created with a human label `name`, a `base_floor_pct`, and an ordered list of `tiers`. The `base_floor_pct` is the lower bound as a fraction of list price below which markdown never pushes the price — for example 0.30 keeps the price at or above thirty percent of list — and it must be greater than zero and at most 1; it defaults to 0.30 when omitted. A `base_floor_pct` that is supplied but is not a number or falls outside the half-open range (0, 1] is a malformed request value and is rejected with `ERR_INVALID_REQUEST`, not `ERR_INVALID_SCHEDULE`; likewise, omitting the `tiers` field entirely is rejected with `ERR_INVALID_REQUEST`. Each entry in `tiers` is a breakpoint of the form `min_age_days` (a whole number of days) paired with a `discount_pct` (a fraction off the list price, where 0.20 means twenty percent off). The schedule's `tiers` must be non-empty, the `min_age_days` values must be strictly increasing, the very first tier must have a `min_age_days` of 0, and every `discount_pct` must be at least 0 and strictly less than 1. A `tiers` value that is present but violates any of these structural rules — including being an empty list, a non-list, or containing an entry with a non-integer `min_age_days` or a non-numeric `discount_pct` — is rejected with `ERR_INVALID_SCHEDULE`. A schedule also carries an `is_archived` flag, which starts false; archiving sets it true. Archiving carries no state precondition and is idempotent: archiving a schedule whose `is_archived` is already true succeeds with `200 OK` and simply leaves the flag true (it still bumps `updated_at` and `version`). An archived schedule may not be attached to a new agreement but remains in force for agreements that already reference it.

A **consignor agreement** ties a consignor to a schedule and pins the economic terms that every item under it will inherit. The `StoreAdmin` creating it supplies the `consignor_id` of an `ACTIVE` consignor, the `markdown_schedule_id` of a non-archived schedule, and a `split_pct`. The `split_pct` is the consignor's share of the split base as a fraction strictly between 0 and 1 — 0.50 means the consignor keeps half and the store keeps the remaining fraction. If the named consignor is not `ACTIVE` or the named schedule is archived, the creation is rejected with `ERR_AGREEMENT_PRECONDITION`. The agreement also fixes four behavioral terms. The `split_basis` is either `GROSS` or `NET` and defaults to `GROSS`; it decides whether the split is taken on the full sale price or on the price net of a per-item processing fee. The `unsold_disposition` is one of `RETURN_TO_CONSIGNOR`, `DONATE`, or `STORE_KEEPS` and defaults to `DONATE`; it decides the fate of items that go unsold past the window. The `return_window_days` is the number of days an item must sit on the floor before it becomes eligible for that disposition; it must be at least 1 and defaults to 90. The `payout_method` is either `CASH` or `STORE_CREDIT` and defaults to `CASH`; it decides whether sale proceeds accrue as cash owed in the payout ledger or are issued as store credit at a bonus rate. An agreement's `status` is `ACTIVE` or `TERMINATED`; it starts `ACTIVE`, and terminating it (which a `StoreAdmin` may do) stops it from accepting any new intake while leaving its existing items untouched. Termination carries no state precondition and is idempotent: terminating an already-`TERMINATED` agreement succeeds with `200 OK` and simply leaves the status `TERMINATED` (it still bumps `updated_at` and `version`).

### 3.2. Intake and Grading

Goods arrive in **intake batches**. An `IntakeGrader` or a `StoreAdmin` opens a batch against an `agreement_id`; the agreement must be `ACTIVE`, and opening a batch under a `TERMINATED` agreement is rejected with `ERR_AGREEMENT_TERMINATED`. A new batch records its `received_at` from the server clock, starts in `OPEN` status, and reports an `item_count` of zero. A batch's `status` is `OPEN` while its garments are being graded and becomes `CLOSED` once grading is finished; closing a batch is an explicit action, after which no further items may be added to it. Unlike termination and archiving, closing is gated on state and is not idempotent: a batch must be `OPEN` to be closed, and attempting to close a batch that is already `CLOSED` is rejected with `ERR_INVALID_STATE`.

Individual garments are added to an `OPEN` batch by an `IntakeGrader` or `StoreAdmin`, who supplies the `batch_id`, a non-empty `title` describing the garment, and an optional `requires_authentication` flag that defaults to false. Adding an item to a `CLOSED` batch is rejected with `ERR_BATCH_CLOSED`. On creation the item copies the `agreement_id` and `consignor_id` down from the batch's agreement so that each garment pins its own split terms. A new item begins with a `grading_status` of `PENDING_GRADE` and a `listing_status` of `NOT_LISTED`. Its `authentication_status` is set to `PENDING_AUTH` when `requires_authentication` is true and to `NOT_REQUIRED` otherwise.

An item carries two independent state dimensions that advance separately. The `grading_status` dimension — the intake and QA pipeline — is one of `PENDING_GRADE`, `ACCEPTED`, or `REJECTED`. The `listing_status` dimension — the floor lifecycle — is one of `NOT_LISTED`, `ON_FLOOR`, `SOLD`, `RETURNED`, `DONATED`, or `PULLED`, and it only begins to advance once grading has accepted the item.

An `IntakeGrader` grades a `PENDING_GRADE` item by submitting a `decision`. The grade endpoint additionally requires `expected_item_version` carrying the grader's last observed `version` of the item, enforced as described in Section 2.8. Grading is only permitted while the item's `grading_status` is `PENDING_GRADE` and its batch is still `OPEN`; an attempt to grade an item that is not in `PENDING_GRADE` is rejected with `ERR_INVALID_STATE`. A `decision` of `ACCEPT` advances the grading dimension `PENDING_GRADE → ACCEPTED`, requires a `list_price_cents` of at least 0 to be supplied as the garment's original list price, and records the grading operator's identifier on `graded_by_user_id`. Accepting without a `list_price_cents` is rejected with `ERR_LIST_PRICE_REQUIRED`. If the accepted item required authentication, its `authentication_status` moves to `PENDING_AUTH`; otherwise it stays `NOT_REQUIRED`. A `decision` of `REJECT` advances the grading dimension `PENDING_GRADE → REJECTED`, the terminal grading outcome, and likewise records `graded_by_user_id`. Both decisions increment the item's `version`.

### 3.3. Authentication and the Separation of Duties

Branded or luxury garments — those whose `requires_authentication` is true — must clear an **authentication review** before they can reach the floor. After such an item has been accepted at grading, an `Authenticator` opens a review by naming the `item_id`; the item must require authentication and must already be `ACCEPTED` at grading. Opening the review records the authenticator's identifier on `opened_by_user_id`, starts the review in `IN_REVIEW` status, sets its `dispute_round` to 0, and initializes its `verdict_note` to null. The `verdict_note` field is always present in a review's serialized form — null until a verdict supplies one — and is populated only when a verdict carries a note (a verdict without a note leaves any prior `verdict_note` unchanged).

A non-negotiable separation-of-duties rule governs authentication: the operator who opens or rules on a review must not be the same person who graded the item. The server compares the acting `X-User-ID` against the item's recorded `graded_by_user_id`, and if they match it rejects the action with `ERR_SEGREGATION_OF_DUTIES`. This check guards both opening a review and recording a verdict on one.

The review's `status` is cyclic. From `IN_REVIEW`, an `Authenticator` records a verdict by submitting a `verdict`, optionally accompanied by a `verdict_note`. A `verdict` of `AUTHENTIC` advances the review `IN_REVIEW → AUTHENTIC` and cascades the item's `authentication_status` to `AUTHENTIC`, which unblocks listing. A `verdict` of `COUNTERFEIT` advances the review `IN_REVIEW → COUNTERFEIT`, sets the item's `authentication_status` to `COUNTERFEIT`, and additionally cascades the item's `grading_status` to `REJECTED`, because counterfeit goods may never be sold. Recording a verdict on a review that is not `IN_REVIEW` is rejected with `ERR_INVALID_STATE`. Between rounds, a `SettlementManager` may dispute an in-review authentication, advancing it `IN_REVIEW → DISPUTED`; an `Authenticator` may then reopen it, advancing it `DISPUTED → IN_REVIEW` and incrementing the review's `dispute_round` by one. This dispute-and-reopen cycle may repeat any number of rounds before a terminal verdict is reached. A dispute is only valid from `IN_REVIEW` and a reopen only from `DISPUTED`; either out of turn is rejected with `ERR_INVALID_STATE`. Every one of these transitions increments the review's `version`.

### 3.4. Putting Items on the Floor and the Markdown Clock

Once an item has been accepted at grading and cleared authentication, an `IntakeGrader` lists it, advancing its listing dimension `NOT_LISTED → ON_FLOOR`. Listing requires the item's `grading_status` to be `ACCEPTED` and its `listing_status` to be `NOT_LISTED` (or `PULLED`, as below); an attempt to list from any other state is rejected with `ERR_INVALID_STATE`. Listing is additionally gated on authentication: the item's `authentication_status` must be either `NOT_REQUIRED` or `AUTHENTIC`. An item still `PENDING_AUTH` or found `COUNTERFEIT` cannot be listed, and the attempt is rejected with `ERR_AUTHENTICATION_REQUIRED`. On listing, the item's `floor_date` is stamped from the server clock — this anchors both the markdown aging and the return window — and its `current_price_cents` is recomputed for an item that has just reached the floor.

The **markdown price** is the heart of the pricing engine. An item's `current_price_cents` is derived from its `list_price_cents`, the time it has spent on the floor, and its agreement's markdown schedule; it is recomputed whenever the item is read, whenever it is listed, and snapshotted at sale time. The computation proceeds as follows. First, the item's age in whole days is the number of seconds between now and its `floor_date`, divided by the number of seconds in a day — 86,400 — and rounded down to a whole number of days; should the clock have been driven to an instant before `floor_date`, that negative elapsed time is clamped to zero so the age is never negative. Next, the applicable tier is selected as a step function: among all tiers whose `min_age_days` is less than or equal to the item's age in days, the one with the greatest `min_age_days` wins. A raw price is then computed by multiplying the `list_price_cents` by one minus that tier's `discount_pct` and rounding the product half up to a whole cent. Independently, a floor price is computed by multiplying the `list_price_cents` by the schedule's `base_floor_pct` and flooring the product to a whole cent. The `current_price_cents` is whichever of the raw price and the floor price is greater. At the moment of listing the item's age is zero days, so the first tier (whose `min_age_days` is 0) always applies; as the item ages, progressively deeper tiers are selected and the price can fall all the way to — but never below — the floor.

While an item is on the floor, an `IntakeGrader` or `StoreAdmin` may pull it off, advancing its listing dimension `ON_FLOOR → PULLED`. Pulling is only allowed while the item is `ON_FLOOR` and has **not** yet passed its return window — that is, the item's age since `floor_date` is strictly less than the agreement's `return_window_days`; an attempt to pull an item already past its window is rejected with `ERR_RETURN_WINDOW_ELAPSED` (the item should be disposed instead). A pulled item can be relisted by an `IntakeGrader`, advancing it `PULLED → ON_FLOOR`; relisting again requires the `authentication_status` to be `NOT_REQUIRED` or `AUTHENTIC`, re-stamps `floor_date` from the server clock so the aging clock restarts from zero, and recomputes `current_price_cents`. Every list, pull, and relist increments the item's `version`.

### 3.5. Ringing a Sale and Splitting the Proceeds

A `CashierClerk` rings a **sale** of one or more on-floor garments by submitting `lines` — an array in which each element names an `item_id` and may optionally carry an explicit `sold_price_cents` — together with an optional `payment_method` that records how the buyer paid (`CASH`, `CARD`, or `STORE_CREDIT`, defaulting to `CARD`). The `payment_method` is purely informational: it is stored verbatim on the sale and never triggers any side effect, so a `STORE_CREDIT` payment does not debit the buyer's store-credit balance or post any `StoreCreditTransaction`. The sale is created in `COMPLETED` status; its `sold_at` is taken from the server clock and its `business_date` is the UTC calendar date (in YYYY-MM-DD form) derived from `sold_at`, which is the key the daily settlement groups on. The clerk's identifier is recorded on `rung_by_user_id`.

The lines are validated in phases rather than one line at a time, each phase scanning every line before the next phase begins, so that when different lines carry different problems the earlier phase's error surfaces: first every line's `item_id` is resolved (an unresolved one yielding `ERR_REFERENCE_NOT_FOUND`), then every line is checked for being on the floor, then the set of lines is checked for duplicates, and only then is each line's price band checked. Every garment named on a line must be `ON_FLOOR` at sale time; a line referencing an item whose `listing_status` is anything else is rejected with `ERR_ITEM_NOT_ON_FLOOR`. The same `item_id` may appear at most once across all the lines of a single sale — no double-ringing one garment — and a duplicate is rejected with `ERR_DUPLICATE_SALE_LINE`. For each line, the price the line actually sells at is `sold_price_cents`; when the clerk omits it, it defaults to the item's current markdown price `current_price_cents`. A clerk may pass a discounted value, but it must lie within the markdown band: it must be at least the markdown floor — the `list_price_cents` multiplied by the schedule's `base_floor_pct`, floored to a whole cent — and at most the item's `current_price_cents`. A `sold_price_cents` below that floor or above the current price is rejected with `ERR_PRICE_BELOW_FLOOR`.

Ringing a sale cascades through the books. For each line the server creates a `SaleLine` capturing its `sale_id`, the `item_id`, and the `consignor_id` copied from the item for ledger attribution, then advances that item's listing dimension `ON_FLOOR → SOLD` and freezes the item's `sold_price_cents` from the line. The sale's `gross_total_cents` is the sum of the `sold_price_cents` across all of its lines. Each line then computes the split. The **split base** — the amount the consignor's percentage is applied to, stored as `split_base_cents` — depends on the agreement's `split_basis`. Under `GROSS` basis the split base equals the line's `sold_price_cents`; the per-line `processing_fee_cents` is ignored and the store absorbs it from its own share. Under `NET` basis the split base is the line's `sold_price_cents` minus its `processing_fee_cents`, but never less than zero — if the fee exceeds the price the base floors at zero. The `processing_fee_cents` is a flat per-line fee taken from store configuration and frozen on the line at sale time; that configured fee is 150 cents.

From the split base, the line's `consignor_proceeds_cents` is the `split_base_cents` multiplied by the agreement's `split_pct`, rounded half up to a whole cent. The line's `store_share_cents` is then the line's `sold_price_cents` minus its `consignor_proceeds_cents`; the store's share is computed by subtraction, not rounded independently, so it absorbs both the processing fee (under gross basis) and any rounding remainder.

### 3.6. Two Payout Channels: Cash Accrual and Store Credit with Bonus

What happens to a line's `consignor_proceeds_cents` after it is computed depends on the agreement's `payout_method`, and the two channels deliberately credit different amounts for identical line inputs.

When the agreement pays out in `CASH`, the sale appends a `PayoutLedgerEntry` for the line with an `entry_type` of `SALE_PAYOUT` and an `amount_cents` equal to the positive `consignor_proceeds_cents`; the entry records the `consignor_id` and stores the originating line's item identifier in `sale_line_ref`. Its `settlement_id` is null until a settlement sweeps it. Creating the entry causes the consignor's `unsettled_payable_cents` to be recomputed.

When the agreement pays out in `STORE_CREDIT`, the proceeds are first upgraded by a tiered bonus before being issued. The **store-credit payout** takes the line's `consignor_proceeds_cents` as its base and adds a bonus that steps with the size of that base. If the base is at least 10,000 cents — that is, one hundred dollars or more — the bonus is the base multiplied by 0.20, rounded half up to a whole cent. Otherwise, if the base is at least 2,000 cents — twenty dollars or more — the bonus is the base multiplied by 0.10, rounded half up. Below 2,000 cents there is no bonus. The boundaries are inclusive: a base of exactly 2,000 cents earns the ten-percent tier, a base of exactly 10,000 cents earns the twenty-percent tier, and a base of 9,999 cents earns only the ten-percent tier. The issued amount is the base plus the bonus. The sale then appends a `StoreCreditTransaction` with a `txn_type` of `ISSUE`, a `status` of `POSTED`, and an `amount_cents` equal to the positive issued amount, recording the `consignor_id`; this causes the consignor's `store_credit_cents` to be recomputed.

Separately from any sale, store credit can be spent. A `CashierClerk` or `StoreAdmin` redeems credit on a consignor's behalf by submitting an `amount_cents` to redeem, which must be an integer of at least 1; an `amount_cents` that is absent, non-integer, or less than 1 is rejected with `ERR_INVALID_REQUEST`. This appends a `StoreCreditTransaction` with a `txn_type` of `REDEEM`, a `status` of `POSTED`, and a negative `amount_cents` equal to the negated requested amount, then recomputes `store_credit_cents`. A redemption that would drive the consignor's posted store-credit balance below zero is rejected with `ERR_INSUFFICIENT_STORE_CREDIT`.

### 3.7. Voiding a Sale: Compensation that Returns to Zero

A sale that was rung in error can be reversed before its settlement closes. A `CashierClerk` or `SettlementManager` voids a `COMPLETED` sale, advancing it `COMPLETED → VOIDED`. A void is only permitted while the sale's `status` is `COMPLETED` and its `settlement_id` is still null — a sale already swept into a finalized settlement cannot be voided, and the attempt is rejected with `ERR_INVALID_STATE`. Voiding cascades the exact inverse of the original sale so the consignor's balance returns to its pre-sale value. For each of the voided sale's lines, the underlying item is returned to the floor — its listing dimension moves `SOLD → ON_FLOOR`, its frozen `sold_price_cents` is cleared, and its `current_price_cents` is recomputed. For lines under a `CASH`-payout agreement, a compensating `PayoutLedgerEntry` is appended with an `entry_type` of `REVERSAL` and an `amount_cents` equal to the negative of that line's `consignor_proceeds_cents`, exactly offsetting the original accrual so the two sum to zero, and the consignor's `unsettled_payable_cents` is recomputed. For lines under a `STORE_CREDIT`-payout agreement, the originating `ISSUE` `StoreCreditTransaction` has its `status` flipped to `VOID` so it drops out of the posted sum, and the consignor's `store_credit_cents` is recomputed. The void increments the sale's `version`.

### 3.8. Unsold Stock: Returns, Donations, and Tax Receipts

Garments that linger past their return window are resolved through disposition. A `SettlementManager` or `StoreAdmin` disposes of an on-floor item only once it has passed its return window — that is, the item's age since `floor_date` is at least the agreement's `return_window_days`; disposing before the window has elapsed is rejected with `ERR_RETURN_WINDOW_NOT_ELAPSED`. The fate of the item follows the agreement's `unsold_disposition`. When the disposition is `RETURN_TO_CONSIGNOR`, the item advances `ON_FLOOR → RETURNED` and a `DonationRecord` is created with a `disposition` of `RETURNED` and a `tax_receipt_value_cents` of 0. When the disposition is `DONATE` or `STORE_KEEPS`, the item advances `ON_FLOOR → DONATED`, and a `DonationRecord` is created whose `disposition` is `DONATED` in the donate case and `STORE_KEPT` in the store-keeps case; the record copies the `consignor_id` and references the originating `item_id`.

The **donation valuation** populates the receipt value. When the resolved `disposition` is `DONATED`, the `tax_receipt_value_cents` is the item's `list_price_cents` multiplied by 0.25 — a twenty-five-percent valuation — floored to a whole cent. For any other disposition, namely `RETURNED` or `STORE_KEPT`, the `tax_receipt_value_cents` is 0, because neither a return nor a store retention yields a charitable deduction. A disposition increments the item's `version`.

### 3.9. The Daily Settlement

At the end of each trading day, a `SettlementManager` reconciles the books with a **daily settlement**. A settlement is opened for a `business_date` (a UTC calendar date in YYYY-MM-DD form) and starts in `OPEN` status with all its totals at zero. At most one non-`VOIDED` settlement may exist for any given `business_date`; opening a second while a non-voided one already covers that date is rejected with `ERR_SETTLEMENT_DATE_TAKEN`. A settlement's `status` is one of `OPEN`, `FINALIZED`, or `VOIDED`. An `OPEN` settlement may be voided by a `SettlementManager`, advancing it `OPEN → VOIDED`, which frees its `business_date` for a fresh settlement; a `FINALIZED` settlement can never be voided.

Finalizing is the consequential step. A `SettlementManager` finalizes an `OPEN` settlement, advancing it `OPEN → FINALIZED`. The finalize endpoint requires `expected_settlement_version` and enforces the optimistic-concurrency check of Section 2.8; finalizing a settlement that is not `OPEN` is rejected with `ERR_INVALID_STATE`, and the precondition that no other finalized settlement already exists for the date is the same uniqueness guard described above. The scope of a finalize is the set of `COMPLETED` sales whose `business_date` equals the settlement's date; `VOIDED` sales are excluded, and any sale already carrying a `settlement_id` from a prior finalize is out of scope.

Over that scope the **settlement rollup** computes five totals. The `total_gross_cents` is the sum of `gross_total_cents` across the in-scope `COMPLETED` sales. The `total_consignor_payable_cents` is the sum of `consignor_proceeds_cents` across every `SaleLine` of the in-scope sales whose agreement pays out in `CASH`. The `total_store_credit_issued_cents` is the sum of the `amount_cents` of the posted `ISSUE` `StoreCreditTransaction` records generated by the in-scope sales. The `total_store_share_cents` is the `total_gross_cents` minus the `total_consignor_payable_cents` minus the `total_store_credit_issued_cents` — the store's net after both payout channels. The `swept_sale_count` is the count of sales swept into the settlement. Each of these sums is taken over per-line values that were already rounded at sale time; the settlement sums those rounded integers and does not re-derive a single split on the gross total and round once — this round-per-line-then-sum ordering is fixed and can differ from a sum-then-round by up to one cent per line.

Finalizing also cascades the sweep. The settlement's `id` is stamped as the `settlement_id` onto every in-scope `COMPLETED` sale and onto every unsettled `PayoutLedgerEntry` whose originating line belongs to those sales. Each affected consignor then has their `unsettled_payable_cents` recomputed — the now-settled entries drop out of it — and their `lifetime_payout_cents` recomputed — the now-settled `SALE_PAYOUT` entries enter it. The finalize sets `swept_sale_count` and increments the settlement's `version`.

A consignor's payout ledger can be read back at any time, and that read accepts a `settled` filter so a caller can narrow it to only the entries already swept into a finalized settlement or only those still outstanding — the same partition that distinguishes `lifetime_payout_cents` from `unsettled_payable_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — registering a consignor, opening a batch, adding an item, opening a review, ringing a sale, redeeming store credit, disposing an item, opening a settlement, or creating a schedule or agreement — return a `201 Created` status code. Operations that modify an existing resource, including every state-transition action (grade, list, pull, verdict, dispute, reopen, terminate, archive, close, finalize, void) and status updates, return a `200 OK` status code. The administrative clock-set capability returns `200 OK`. The request and response bodies for each operation are described in Sections 2 and 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/consignors` | Register a consignor | StoreAdmin |
| GET | `/consignors/{id}` | Read a consignor with reconciled derived balances | StoreAdmin, SettlementManager, CashierClerk, IntakeGrader, Authenticator |
| GET | `/consignors` | List consignors (filterable by status) | StoreAdmin, SettlementManager |
| PATCH | `/consignors/{id}` | Update consignor status | StoreAdmin |
| GET | `/consignors/{id}/agreements` | List agreements for a consignor | StoreAdmin, SettlementManager |
| GET | `/consignors/{id}/ledger-entries` | List payout ledger entries for a consignor | StoreAdmin, SettlementManager |
| GET | `/consignors/{id}/store-credit/transactions` | List store-credit transactions for a consignor | StoreAdmin, SettlementManager |
| GET | `/consignors/{id}/sale-lines` | List sale lines attributed to a consignor | StoreAdmin, SettlementManager |
| POST | `/consignors/{id}/store-credit/redeem` | Redeem store credit | CashierClerk, StoreAdmin |
| POST | `/markdown-schedules` | Create a markdown schedule | StoreAdmin |
| GET | `/markdown-schedules/{id}` | Read a markdown schedule | StoreAdmin, SettlementManager, IntakeGrader |
| POST | `/markdown-schedules/{id}/archive` | Soft-archive a schedule | StoreAdmin |
| POST | `/agreements` | Create a consignor agreement | StoreAdmin |
| GET | `/agreements/{id}` | Read an agreement | StoreAdmin, SettlementManager, IntakeGrader, CashierClerk |
| GET | `/agreements` | List agreements (filterable by consignor_id, markdown_schedule_id, status) | StoreAdmin, SettlementManager |
| POST | `/agreements/{id}/terminate` | Terminate an agreement | StoreAdmin |
| GET | `/agreements/{id}/intake-batches` | List intake batches under an agreement | StoreAdmin, SettlementManager, IntakeGrader |
| POST | `/intake-batches` | Open an intake batch | IntakeGrader, StoreAdmin |
| GET | `/intake-batches/{id}` | Read a batch with derived item_count | IntakeGrader, StoreAdmin, SettlementManager |
| POST | `/intake-batches/{id}/close` | Close a batch | IntakeGrader, StoreAdmin |
| GET | `/intake-batches/{id}/items` | List items in a batch | IntakeGrader, StoreAdmin, SettlementManager |
| POST | `/items` | Add an item to an OPEN batch | IntakeGrader, StoreAdmin |
| GET | `/items/{id}` | Read an item with recomputed current_price_cents | IntakeGrader, StoreAdmin, SettlementManager, CashierClerk, Authenticator |
| GET | `/items` | List items (filterable by consignor_id, agreement_id, listing_status, grading_status) | IntakeGrader, StoreAdmin, SettlementManager, CashierClerk |
| POST | `/items/{id}/grade` | Grade an item ACCEPT or REJECT | IntakeGrader |
| POST | `/items/{id}/list` | Put an item on the floor | IntakeGrader |
| POST | `/items/{id}/pull` | Pull an on-floor item off the floor | IntakeGrader, StoreAdmin |
| POST | `/items/{id}/dispose` | Dispose an unsold item past its return window | SettlementManager, StoreAdmin |
| GET | `/items/{id}/authentication-reviews` | List authentication reviews for an item | Authenticator, IntakeGrader, StoreAdmin, SettlementManager |
| GET | `/items/{id}/donation-record` | List the donation record for a disposed item | SettlementManager, StoreAdmin |
| GET | `/items/{id}/sale-lines` | List sale lines referencing an item | CashierClerk, SettlementManager, StoreAdmin |
| POST | `/authentication-reviews` | Open an authentication review | Authenticator |
| GET | `/authentication-reviews/{id}` | Read an authentication review | Authenticator, SettlementManager, StoreAdmin, IntakeGrader |
| POST | `/authentication-reviews/{id}/verdict` | Rule a review AUTHENTIC or COUNTERFEIT | Authenticator |
| POST | `/authentication-reviews/{id}/dispute` | Dispute an in-review authentication | SettlementManager, StoreAdmin |
| POST | `/authentication-reviews/{id}/reopen` | Reopen a disputed review | Authenticator |
| POST | `/sales` | Ring a sale of one or more on-floor items | CashierClerk |
| GET | `/sales/{id}` | Read a sale | CashierClerk, SettlementManager, StoreAdmin |
| GET | `/sales` | List sales (filterable by business_date, status, settlement_id) | CashierClerk, SettlementManager, StoreAdmin |
| GET | `/sales/{id}/lines` | List sale lines under a sale | CashierClerk, SettlementManager, StoreAdmin |
| POST | `/sales/{id}/void` | Void an unsettled completed sale | CashierClerk, SettlementManager |
| POST | `/settlements` | Open a daily settlement | SettlementManager |
| GET | `/settlements/{id}` | Read a settlement | SettlementManager, StoreAdmin |
| GET | `/settlements` | List settlements (filterable by business_date, status) | SettlementManager, StoreAdmin |
| POST | `/settlements/{id}/finalize` | Finalize a settlement | SettlementManager |
| POST | `/settlements/{id}/void` | Void an OPEN settlement | SettlementManager |
| GET | `/settlements/{id}/sales` | List sales swept into a settlement | SettlementManager, StoreAdmin |
| GET | `/settlements/{id}/ledger-entries` | List ledger entries swept into a settlement | SettlementManager, StoreAdmin |
| GET | `/donation-records/{id}` | Read a donation record | SettlementManager, StoreAdmin |
| GET | `/donation-records` | List donation records (filterable by consignor_id, disposition) | SettlementManager, StoreAdmin |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC instant | StoreAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_ITEM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SETTLEMENT_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AUTHENTICATION_REQUIRED` | 409 Conflict |
| `ERR_ITEM_NOT_ON_FLOOR` | 409 Conflict |
| `ERR_DUPLICATE_SALE_LINE` | 409 Conflict |
| `ERR_RETURN_WINDOW_NOT_ELAPSED` | 409 Conflict |
| `ERR_RETURN_WINDOW_ELAPSED` | 409 Conflict |
| `ERR_PRICE_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_DATE_TAKEN` | 409 Conflict |
| `ERR_INSUFFICIENT_STORE_CREDIT` | 422 Unprocessable Entity |
| `ERR_INVALID_SCHEDULE` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_AGREEMENT_PRECONDITION` | 409 Conflict |
| `ERR_BATCH_CLOSED` | 409 Conflict |
| `ERR_AGREEMENT_TERMINATED` | 409 Conflict |
| `ERR_LIST_PRICE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_VALIDATION_PAGINATION` | 400 Bad Request |
