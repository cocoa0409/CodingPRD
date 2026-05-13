# Live Stream Schedule API — Product Requirements Document

## 1. Introduction

E-commerce live streaming has become a primary distribution channel, but the back office that supports it remains fragile: streamers, studios, products, schedules, fees, commissions, and penalties each live in their own spreadsheets, and the people who must coordinate them — streamers, operations reviewers, compliance reviewers, and platform admins — have no single source of truth. This document specifies the **Live Stream Schedule** service, a unified REST API that ties the full lifecycle together, from streamer onboarding through slot booking, multi-level review, broadcast execution, commission settlement, and violation enforcement.

The service serves four classes of caller. A streamer applies for time slots, attaches products, runs broadcasts, and files appeals against penalties. An operations reviewer performs the first-line check that the application's products and qualifications are coherent. A compliance reviewer performs the second-line legal and safety review, decides appeals, and is the only role that finalizes a slot and pins its fee. A platform admin manages the catalog (streamers, studios, products), pays out settlements, and drives the time-based machinery (clock advance, periodic sweep, and external-event injection) on which the rest of the platform depends.

The system is opinionated about three things: time is a first-class quantity (every state transition checks the simulated clock against application intervals, return windows, appeal windows, and suspension expiry); money is computed by the server with single-rounding integer-cent arithmetic, never by clients; and side effects cascade — a single compliance approval pins a fee, schedules a broadcast, issues an invoice, and arms a downstream commission settlement, while a single appeal overturn may reverse a fine, lift a suspension, restore a tier, and propagate the change to every future-scheduled application.

## 2. Global Specifications & System-Wide Principles

All endpoints described in this document are mounted under the URL prefix `/live-schedule`. The rules in this section apply to every endpoint unless §3 explicitly narrows them.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. Either header missing yields `ERR_AUTH_REQUIRED` with HTTP 401. A header pair whose role is not authorized for the requested endpoint yields `ERR_FORBIDDEN` with HTTP 403.

The system defines exactly four roles: `Streamer`, `OperationsReviewer`, `ComplianceReviewer`, and `PlatformAdmin`. The identity contract differs across them:

- When `X-User-Role` is `Streamer`, `X-User-ID` is the `id` of the acting `Streamer` entity. Every ownership check on a resource that references a streamer compares the resource's `streamer_id` field to `X-User-ID`; a `Streamer` reading or mutating another streamer's resource is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `OperationsReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on artifacts such as `ApprovalRecord.reviewer_id` and `AuditLog.actor_id`, but never compares it against any entity's `id`.
- When `X-User-Role` is `ComplianceReviewer`, `X-User-ID` is likewise an opaque operator identifier; the server records it on artifacts such as `ApprovalRecord.reviewer_id` and `AuditLog.actor_id` without entity-comparison.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier; it appears in `AuditLog.actor_id` but is never compared to any entity's `id`.

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

Every list endpoint accepts two query parameters: `limit` and `offset`. The default `limit` is 10 and the default `offset` is 0. The minimum `limit` is 1 and the maximum is 100; the minimum `offset` is 0 and there is no upper bound. A value outside the allowed range yields `ERR_PAGINATION_INVALID` with HTTP 400.

List endpoints return their items in ascending `created_at` order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of items matching the filter (before pagination is applied) and `has_more` is true exactly when `offset + len(returned items) < total_count`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource carries a server-minted UUID `id` field. The `id` is a bare UUID string with no type prefix.

For most entities — `Streamer`, `Studio`, `ScheduleApplication`, `Product`, `ProductAssociation`, `SlotFeeInvoice`, `CommissionSettlement`, `Violation`, `Appeal` — the server also stamps `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits, and maintains a `version` integer that starts at 1 on creation and increments by 1 on every mutation. The lightweight log-style entities `TimeSlotConfig`, `ApprovalRecord`, `ExternalEvent`, and `AuditLog` carry only `id` and `created_at`; they have neither `updated_at` nor `version` because they are append-only and never mutated after their initial write.

Mutating endpoints on the heavyweight entities accept an optional `version` field in the request body. When present, the value must equal the entity's current `version` integer; a mismatch is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When omitted, the OCC check is skipped and the mutation proceeds. Every successful mutation increments `version` by 1 and refreshes `updated_at` to the current server clock.

### 2.5. Temporal Model and the Logical Clock

The platform reads "now" from a server-managed simulated clock. Every temporal precondition in this document — interval overlap checks, return-window expiry, appeal-window expiry, suspension reconciliation, cancel-before-start gating — resolves against this logical clock, not the host system clock. An admin-only test-driving capability advances the clock to a supplied `to` instant; a separate read-only capability reports the current value. All datetime fields exchanged with the API are ISO 8601 UTC with three fractional digits.

Every interval declared by the system — a time-slot configuration's `starts_at`/`ends_at`, a maintenance window, an application's `starts_at`/`ends_at`, an existing approved or live application — is **half-open**: the start is inclusive and the end is exclusive. Two intervals are considered to overlap exactly when the start of one is strictly less than the end of the other and vice versa; a back-to-back pair where one ends at the same instant another begins does not overlap.

### 2.6. Nested Resource Retrieval and Path Resolution

Path parameters are resolved left to right. If a path segment names an entity that does not exist (a streamer id, application id, studio id, product id, settlement id, violation id, or appeal id), the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first unresolved segment. Body-referenced ids on creation endpoints (notably `studio_id`, `streamer_id`, `product_id`, and `application_id`) are likewise verified to resolve to live entities before any business logic runs; an unresolved body id also yields `ERR_NOT_FOUND`.

### 2.7. Slot Fee, Deposit, and Commission Precision

All monetary fields are stored in **integer cents**. Calculations carry intermediate values at full precision and apply **round-half-up to integer cents exactly once at the end** — not per discount step, not per peak-minute, not per commission line. Where a calculation produces an integer threshold check on an unrounded intermediate (for example, comparing effective sales to the tier-bonus floor), the comparison is performed on the unrounded value.

The deposit fraction is fixed at 30% of the final slot fee, with the single end-of-calculation rounding applied. The peak surcharge multiplier is 0.50 of the base hourly price, applied to the fraction of the booked interval that falls inside the peak window of 19:00–23:00 UTC. The tier-based commission rate is denominated in basis points and divided by 10,000 to convert to a fractional rate. Tax is withheld at a flat 10% of the positive commission base.

### 2.8. Cascading Side Effects and Version Bumps

A single business action frequently mutates more than one entity. Whenever the server mutates a heavyweight entity as part of a cascade, that entity's `version` increments by 1 and its `updated_at` refreshes to the current logical clock; the cascade does not "batch" version bumps. Notable depth-3 cascades appear in §3 (the `Streamer.tier` recompute that follows a broadcast completion, the appeal overturn that walks back through `violation_score` and tier to suspension state, and the sweep that propagates a violation enforcement through streamer status into future-scheduled applications and their invoices). Wherever a parent entity transitions, any pinned snapshot fields on its children (for example, `pinned_streamer_tier` on the application or `snapshot_streamer_tier` on an approval record) are preserved exactly as captured — recomputing the parent's `tier` after the snapshot was taken does not retroactively rewrite the snapshot.

### 2.9. Validation Priority

When multiple validations could apply to a single request, the server evaluates them in a fixed order so that the returned `error_id` is predictable. The authentication-headers check fires first (`ERR_AUTH_REQUIRED`), then the role-authorization check (`ERR_FORBIDDEN`), then path-id existence (`ERR_NOT_FOUND`), then body-id existence (`ERR_NOT_FOUND`), then streamer-ownership (`ERR_FORBIDDEN`), then state precondition (`ERR_INVALID_STATE`). Beyond these six gating checks, business rules are evaluated in the order in which they appear in §3's workflow narratives — for example, on submit the streamer-active check precedes the qualification check, which precedes the time-window check, which precedes the studio-overlap check; on a product association the certification check precedes the category-match check, which precedes the on-shelf check, which precedes the stock check. The OCC version check, when a `version` field is supplied, runs after the gating six but before any side-effecting business logic, so a stale-version request never accidentally consumes a one-shot operation.

## 3. Business Logic & Workflows

### 3.1. Streamer Lifecycle and the Performance Tier

A streamer is admitted to the platform by a `PlatformAdmin` who supplies the candidate's `legal_name`, `id_card_number`, the initial `real_name_verified` flag, a `health_cert_expires_at` timestamp, a list of `professional_cert_categories` the streamer is certified to broadcast (codes such as `FOOD`, `COSMETICS`, `ELECTRONICS`, `FASHION`, `KIDS`, `FINANCIAL`), and a list of declared `content_category_tags`. The `id_card_number` is unique across active streamers — re-registering an `id_card_number` that is already attached to an active record is rejected. On creation the server initializes `tier` to `BRONZE`, `violation_score` to 0, `lifetime_gmv_cents` to 0, `completed_broadcast_count` to 0, `status` to `ACTIVE`, and leaves `suspension_until` null.

The `tier` is the lever that ties performance back into pricing and payout. It is recomputed whenever a broadcast reaches `COMPLETED` and whenever an appeal overturns a penalty that previously moved the `violation_score`. The recompute applies a strict ladder, evaluated top to bottom on the current `Streamer.lifetime_gmv_cents` and `Streamer.violation_score`: if the violation score is at least 50 or the streamer is `BLACKLISTED`, the tier collapses to `BRONZE`; otherwise, if lifetime GMV is at least 50,000,000 cents and the violation score is at most 5, the tier becomes `PLATINUM`; otherwise, if lifetime GMV is at least 10,000,000 cents and the violation score is at most 10, the tier becomes `GOLD`; otherwise, if lifetime GMV is at least 1,000,000 cents and the violation score is at most 20, the tier becomes `SILVER`; in every other case the tier is `BRONZE`.

A streamer's `status` cycles through `ACTIVE`, `SUSPENDED`, and `BLACKLISTED`. While `ACTIVE`, the streamer may submit, run, and complete broadcasts. While `SUSPENDED`, the server records a `suspension_until` instant and refuses streamer-initiated mutations (submit, start-live, association create) with `ERR_STREAMER_NOT_ACTIVE` (HTTP 403); the periodic sweep returns the streamer to `ACTIVE` once the logical clock advances past `suspension_until`. While `BLACKLISTED`, the same gate applies and `suspension_until` is null; no sweep restores the streamer.

### 3.2. Studios, Time Slots, and Maintenance Windows

A `PlatformAdmin` registers each studio with its display `name`, `location`, an `equipment_inventory` array (camera, lighting, audio, teleprompter SKUs), an integer `capacity` of at least 1, a `studio_type` of either `SELF_OPERATED` or `PARTNER`, a `slot_tier` from `S`, `A`, `B`, `C`, and an integer `base_hour_price_cents` of at least 0. The studio starts in `status` `OPEN`; admins may move it to `RESTRICTED`, `UNDER_MAINTENANCE`, or `CLOSED` through an OCC-protected update that accepts optional `status`, optional `capacity`, and an optional `version` field.

Each studio's bookable calendar is built from `TimeSlotConfig` rows attached to it. Each row carries a `kind` of either `AVAILABLE` or `MAINTENANCE`, a `starts_at` (inclusive) and `ends_at` (exclusive), and a `weekday_mask` — a 7-bit integer interpreted as Monday-through-Sunday recurrence (0 means a one-off, non-recurring window). When a streamer requests an interval, the server first verifies the studio's overall `status` is `OPEN`; if not, the submit is rejected with `ERR_INVALID_STATE`. It then verifies that every minute of the requested half-open interval is covered by at least one `AVAILABLE` `TimeSlotConfig` and intersects no `MAINTENANCE` `TimeSlotConfig`; a violation yields `ERR_OUT_OF_AVAILABLE_WINDOW` (HTTP 409).

### 3.3. Product Catalog and Stock Reservation

The product catalog is curated by a `PlatformAdmin`. Each product carries a display `name`, a `category` drawn from `FOOD`, `COSMETICS`, `ELECTRONICS`, `FASHION`, `KIDS`, `FINANCIAL`, a boolean `requires_professional_cert` flag, an integer `unit_price_cents` of at least 0, and an integer `available_stock` of at least 0. On creation the server sets `status` to `ON_SHELF` and `reserved_stock` to 0. Admins move stock and listing state through an OCC-protected update that takes optional `status`, optional `available_stock`, and an optional `version`.

When a streamer attaches a product to an application, the request carries the `product_id` and a `reserved_quantity` of at least 1; the server decrements the product's `available_stock` by `reserved_quantity` and increments its `reserved_stock` by the same amount, then runs the eligibility ladder described below. If the application is still in pre-approval review (`review_status` of `DRAFT`, `OPS_PENDING`, or `COMPLIANCE_PENDING`), the resulting `ProductAssociation` receives `association_phase` `PRE_APPROVAL`; otherwise the association is recorded with `association_phase` `DURING_BROADCAST`.

Two streamers racing to reserve stock from the same product are serialized first-writer-wins on the product row: the cumulative `reserved_quantity` across all non-`RELEASED` associations may not exceed `Product.available_stock + Product.reserved_stock` at submission time. The loser receives `ERR_STOCK_INSUFFICIENT` (HTTP 409).

The product-eligibility ladder is evaluated in strict order, and the first failing rule pins the association's `reject_reason`. The product must currently be `ON_SHELF` — if its `status` is `OFF_SHELF`, the association is rejected with `reject_reason` `NOT_ON_SHELF` and `ERR_PRODUCT_NOT_ON_SHELF` (HTTP 422). The product's `category` must appear in the application's `declared_product_categories` — otherwise `reject_reason` is `CATEGORY_MISMATCH` and the response is `ERR_PRODUCT_CATEGORY_MISMATCH` (HTTP 422). If the product's `requires_professional_cert` is true, the product's `category` must appear in the streamer's `professional_cert_categories` list — otherwise `reject_reason` is `MISSING_CERT` and the response is `ERR_PRODUCT_CERT_MISSING` (HTTP 422). Finally the requested `reserved_quantity` must not exceed the product's current `available_stock` — otherwise `reject_reason` is `STOCK_INSUFFICIENT` and the response is `ERR_STOCK_INSUFFICIENT` (HTTP 409). When the ladder is failed, the server immediately re-releases the stock it had pre-decremented (the product's `reserved_stock` decreases by `reserved_quantity` and `available_stock` increases by the same amount), records the association with `status` `REJECTED`, and pins the `reject_reason` accordingly. When the ladder passes, the association is recorded with `status` `APPROVED`.

The same eligibility ladder is re-run by the operations reviewer at the first level of approval. An application cannot be promoted from `OPS_PENDING` to `COMPLIANCE_PENDING` until every `ProductAssociation` row for it is in `status` `APPROVED` and still passes the four-step ladder against the streamer's current `professional_cert_categories` and the products' current `status` and `available_stock`. A failure surfaces with the same error ids as at association time.

### 3.4. Application Submission and the Two-Level Review

A streamer initiates an `ScheduleApplication` by supplying `streamer_id` (which must equal `X-User-ID`), `studio_id`, the desired `starts_at` and `ends_at`, an array of `declared_content_categories`, an array of `declared_product_categories`, and a `package_code` from `STANDARD`, `COMBO_HALF_DAY`, `COMBO_FULL_DAY`, or `PEAK_BUNDLE` (defaulting to `STANDARD`). The interval must satisfy `ends_at > starts_at` and the difference between `ends_at` and `starts_at` must be at least 30 minutes and at most 8 hours — outside that range the create is rejected with `ERR_INVALID_INTERVAL` (HTTP 422). The fresh application carries `review_status` `DRAFT` and `operational_status` `NOT_SCHEDULED`.

After attaching products, the streamer advances the application from `DRAFT` to `OPS_PENDING`. The submit checks, evaluated in the priority order described in §2.9: the acting streamer owns the application (otherwise `ERR_FORBIDDEN`); the streamer's `status` is `ACTIVE` (otherwise `ERR_STREAMER_NOT_ACTIVE`); the streamer's `real_name_verified` is true and the streamer's `health_cert_expires_at` is strictly later than the application's `ends_at` (otherwise `ERR_QUALIFICATION_MISSING`, HTTP 422); the studio's `status` is `OPEN`; the requested interval is fully covered by `AVAILABLE` `TimeSlotConfig` rows and disjoint from every `MAINTENANCE` window using half-open overlap (otherwise `ERR_OUT_OF_AVAILABLE_WINDOW`); and the interval does not overlap any existing application of the same `Studio` whose `review_status` is `APPROVED` or whose `operational_status` is `SCHEDULED` or `LIVE` (otherwise `ERR_STUDIO_INTERVAL_CONFLICT`, HTTP 409). On success the server computes the provisional slot fee (described below) and writes it to `provisional_fee_cents`, persists the application, and emits an audit record.

An `OperationsReviewer` makes the first review decision. An approval transitions `review_status` from `OPS_PENDING` to `COMPLIANCE_PENDING`, but only if every `ProductAssociation` row on the application is currently `APPROVED` and still passes the four-step product eligibility ladder; a re-check failure surfaces with the corresponding product error. A rejection transitions `review_status` from `OPS_PENDING` to `REJECTED`, requires a non-empty `reason` (otherwise `ERR_REASON_REQUIRED`, HTTP 422), and triggers a uniform release across every `ProductAssociation` for the application: each association moves to `status` `RELEASED`, the product's `reserved_stock` decreases by the association's `reserved_quantity`, and the product's `available_stock` increases by the same amount. The application's `provisional_fee_cents` is set to 0 and no invoice is issued. Both the approve and reject branches insert an `ApprovalRecord` whose `level` is `OPS`, whose `decision` is `APPROVE` or `REJECT`, whose `reviewer_role` is `OperationsReviewer`, and whose `reviewer_id` mirrors `X-User-ID`; `snapshot_streamer_tier` and `snapshot_provisional_fee_cents` are pinned at decision time and are immutable thereafter. A rejection additionally records the supplied `reason`. The two ops reviewers racing to approve the same application are serialized by the application's `version`: the loser fails with `ERR_VERSION_CONFLICT` because the winner has already incremented the version.

A `ComplianceReviewer` then makes the second decision. An approval transitions `review_status` from `COMPLIANCE_PENDING` to `APPROVED` and is the most consequential transition in the system. The compliance approve re-checks two state preconditions and one fiscal precondition: no other application on the same studio has been promoted to `APPROVED`/`SCHEDULED`/`LIVE` in the same interval (otherwise `ERR_STUDIO_INTERVAL_CONFLICT`, HTTP 409); the streamer's `status` is still `ACTIVE` (otherwise `ERR_STREAMER_NOT_ACTIVE`); and the streamer's `violation_score` is strictly less than 100 (otherwise `ERR_STREAMER_BLOCKED`, HTTP 422). On success the server pins `pinned_streamer_tier` to the streamer's current `tier`, computes `final_fee_cents` against that pinned tier (the final variant of the slot-fee calculation), computes `deposit_cents` as 30% of `final_fee_cents` with the single end-of-calculation rounding, issues a `SlotFeeInvoice` (described below) whose `total_cents` equals `final_fee_cents` and whose `deposit_due_cents` equals `deposit_cents` and whose `status` is `ISSUED`, transitions the application's `operational_status` from `NOT_SCHEDULED` to `SCHEDULED`, and inserts an `ApprovalRecord` of `level` `COMPLIANCE`. The compliance approve request body may carry an optional `version` field for OCC; mismatch yields `ERR_VERSION_CONFLICT`. A compliance rejection transitions to `REJECTED`, requires non-empty `reason` (otherwise `ERR_REASON_REQUIRED`), runs the same product-release cascade, and inserts a compliance-level `ApprovalRecord`. Compliance approve and a concurrent streamer withdraw on the same application serialize first-writer-wins on `review_status`; the loser receives `ERR_INVALID_STATE` (HTTP 409).

A streamer may withdraw their own application from `DRAFT` or `OPS_PENDING`, transitioning `review_status` to `WITHDRAWN`. Withdrawal releases every `ProductAssociation` (same release semantics as the ops-reject release: each association's `status` becomes `RELEASED`, the product's `reserved_stock` decreases, the product's `available_stock` increases).

### 3.5. Slot Fee Calculation — Provisional and Final

The slot-fee calculation runs in two variants: a **provisional** variant at submit time (writing `provisional_fee_cents`) and a **final** variant at compliance approval (writing `final_fee_cents`, which must equal the invoice's `total_cents`). The two variants share the same arithmetic and differ only in which streamer tier they use as input — the provisional variant reads the streamer's `tier` as it stands at submission, while the final variant reads `pinned_streamer_tier`, which is the snapshot the compliance approval just pinned. Whenever the streamer's `tier` escalates between submit and compliance approval, the two variants produce different integer-cent results.

The arithmetic proceeds as follows. The number of hours in the requested broadcast, kept at full precision, is the difference between `ends_at` and `starts_at` expressed in seconds and divided by 3600. Multiplying that hour count by the studio's `base_hour_price_cents` produces the base component. The number of peak hours in the interval is the count of minutes in the half-open interval that fall inside the peak window 19:00–23:00 UTC, divided by 60 — kept at full precision, not rounded. Multiplying the peak-hour count by `base_hour_price_cents` and by the peak multiplier 0.50 produces the peak surcharge component. Their sum is the unrounded subtotal.

Two percentage discounts then apply in a strict order. The tier discount comes first: 0% for `BRONZE`, 5% for `SILVER`, 10% for `GOLD`, 15% for `PLATINUM`. The subtotal is multiplied by one minus the tier discount fraction. The package discount applies second, to the tier-adjusted subtotal: 0% for `STANDARD`, 8% for `COMBO_HALF_DAY`, 12% for `COMBO_FULL_DAY`, 5% for `PEAK_BUNDLE`. The package-adjusted value is multiplied by one minus the package discount fraction. The result is then rounded half-up to integer cents **exactly once**, at the very end — order of the two discounts matters because the package discount is taken on top of the tier-adjusted subtotal, not on the original unrounded subtotal.

When `SlotFeeInvoice` is issued at compliance approval, its `subtotal_cents` records the base plus peak-surcharge sum, its `peak_surcharge_cents` records only the peak component, its `package_discount_cents` records the absolute cent reduction attributable to the package discount, and its `total_cents` equals `final_fee_cents`. The invoice's `deposit_due_cents` is then the single-rounded 30% of `total_cents`.

### 3.6. Deposit Payment, Broadcast Execution, and Completion

Once the invoice exists in `status` `ISSUED`, the deposit must be paid through an externally sourced payment event before the streamer is allowed to go live. A platform admin injects a payment event whose `source` is `PAYMENT`, whose `kind` is `DEPOSIT_PAID`, whose `application_id` targets the application, whose `amount_cents` exactly equals the invoice's `deposit_due_cents`, and whose `occurred_at` carries the event time. On a successful match the invoice transitions from `ISSUED` to `DEPOSIT_PAID` and the application's `deposit_paid` is set to true.

Starting the broadcast transitions `operational_status` from `SCHEDULED` to `LIVE`. The acting streamer must own the application, the logical clock must be at or after the application's `starts_at` and strictly before `ends_at`, the invoice must be in `status` `DEPOSIT_PAID` or `SETTLED` (equivalently `deposit_paid` must be true; otherwise `ERR_DEPOSIT_UNPAID`, HTTP 422), and the streamer's `status` must be `ACTIVE`. Ending the broadcast transitions `operational_status` from `LIVE` to `COMPLETED` and requires only that the acting streamer owns the application and that the logical clock is at or after the application's `starts_at`. The end-live transition is the densest cascade in the system: the server initializes a `CommissionSettlement` for the application with `status` `WINDOW_OPEN` and `return_window_ends_at` equal to the application's `ends_at` plus 7 days; it pins the settlement's `commission_rate_bp` using the provisional variant of the commission calculation against `pinned_streamer_tier` and `gmv_cents`; it increments the streamer's `completed_broadcast_count` by 1; and it triggers a depth-3 recompute of `Streamer.tier` (the completion may push `lifetime_gmv_cents` or `violation_score` past a threshold, the recompute may escalate `tier`, and any tier escalation past the `BRONZE` floor causes the sweep's suspension reconciliation to re-evaluate `suspension_until`). The auto-transition from the invoice's `DEPOSIT_PAID` to `SETTLED` fires the same moment the application's `operational_status` advances to `COMPLETED`.

A LIVE broadcast may add new product associations on the fly: the request supplies `product_id` and `reserved_quantity`, and the resulting `ProductAssociation` records `association_phase` `DURING_BROADCAST`. During-broadcast associations are gated by an extra rule: the product's `category` must already appear in the application's `declared_product_categories`, and the total number of `ProductAssociation` rows for the application (across both phases) must remain at most 20. Violating either constraint yields `ERR_LIVE_ASSOCIATION_DENIED` (HTTP 422).

### 3.7. Cancellation, Refunds, and Force-Cancel

A streamer or operations reviewer may cancel a `SCHEDULED` application before it starts, supplying a non-empty `reason`. Cancellation requires the logical clock to be strictly before the application's `starts_at`; an attempted cancel at or after that instant is rejected with `ERR_TOO_LATE_TO_CANCEL` (HTTP 409). A missing `reason` yields `ERR_REASON_REQUIRED`. The cancel cascade transitions `operational_status` from `SCHEDULED` to `CANCELLED`, runs the refund calculation, applies the result to the invoice, and releases every `ProductAssociation` (each becomes `RELEASED`, with the matching `reserved_stock`/`available_stock` adjustment on the product).

The refund calculation reads the lead time as the difference between the application's `starts_at` and "now" expressed in seconds and divided by 3600. If the lead time is at least 72 hours, the refund equals 100% of the invoice's `deposit_due_cents`. If the lead time is at least 24 hours but less than 72 hours, the refund equals one half of `deposit_due_cents`, rounded half-up to integer cents. If the lead time is less than 24 hours, the refund is 0. The refund amount is written to the invoice's `refund_cents`. When the refund equals the full `deposit_due_cents`, the invoice transitions from `DEPOSIT_PAID` to `REFUNDED_FULL`; when the refund is strictly positive but less than `deposit_due_cents`, it transitions to `REFUNDED_PARTIAL`; when the cancellation occurs while the deposit was unpaid (invoice still in `ISSUED`), the invoice transitions from `ISSUED` to `REFUNDED_FULL` with `refund_cents` set to 0 because nothing was paid.

Force-cancellation is the operations-reviewer-only path that may terminate a broadcast mid-`LIVE`. The transition moves `operational_status` from `LIVE` to `CANCELLED`. A force-cancel does not refund the deposit — the invoice's `refund_cents` is set to 0 — and it releases every `ProductAssociation`.

### 3.8. Commission Settlement and Payout

The `CommissionSettlement` arms at end-live with `status` `WINDOW_OPEN` and stays open through the 7-day return window. During that window external `BROADCAST_GMV` events (`source` `ECOMMERCE`, `kind` `BROADCAST_GMV`, targeted by `application_id`) are aggregated into `gross_sales_cents`, and external `RETURN_REPORTED` events are aggregated into `returned_sales_cents` — provided the event's `occurred_at` is at or before the settlement's `return_window_ends_at`; events whose `occurred_at` falls after the window are ignored for settlement purposes.

The commission calculation has the same two-variant shape as the slot fee. The **provisional** variant runs at end-live and reads only `gross_sales_cents` (returns have not yet been collected). It looks up the per-tier rate in basis points — 1,200 for `BRONZE`, 1,500 for `SILVER`, 1,800 for `GOLD`, 2,200 for `PLATINUM` — and pins it to `commission_rate_bp` based on `pinned_streamer_tier`. The gross commission is `gross_sales_cents` multiplied by the rate divided by 10,000, rounded half-up to integer cents, and is recorded on the application's `gross_commission_cents`. The tier bonus is 0 unless `pinned_streamer_tier` is `GOLD` or `PLATINUM` and `gross_sales_cents` is at least 5,000,000 cents, in which case the bonus is half a percent of `gross_sales_cents` (i.e., `gross_sales_cents` multiplied by 0.005), rounded half-up to integer cents, and is recorded on the settlement's `tier_bonus_cents`. The provisional payout is the sum of the gross commission and the tier bonus, written to `provisional_payout_cents`.

The **final** variant runs when the periodic sweep observes a settlement whose `return_window_ends_at` has reached or passed the logical clock. Effective sales are computed as `gross_sales_cents` minus `returned_sales_cents`. The commission to be reversed is `returned_sales_cents` multiplied by the pinned rate divided by 10,000, rounded half-up; the adjusted gross commission is the previously rounded gross commission minus this reversed amount. The adjusted tier bonus is recomputed against **effective sales**, not gross sales: if `pinned_streamer_tier` is `GOLD` or `PLATINUM` and effective sales are at least 5,000,000 cents, the adjusted bonus is half a percent of effective sales rounded half-up; otherwise 0. The pre-tax commission base is the sum of the adjusted gross and the adjusted bonus. When that base is strictly positive, tax is withheld at 10% of the base, rounded half-up, written to `tax_withholding_cents`; when the base is zero or negative, no tax is withheld. The final payout is the pre-tax base minus the tax, written to `final_payout_cents`, and is also reflected on the application's `net_payout_cents`.

When `final_payout_cents` is non-negative, the settlement transitions from `WINDOW_OPEN` to `READY_FOR_PAYOUT`. When `final_payout_cents` is strictly less than 0, the settlement transitions to `REVERSED` instead, and the streamer's `violation_score` is incremented by 1 as a soft penalty for net-negative outcomes. A `PlatformAdmin` then pays out a `READY_FOR_PAYOUT` settlement; the payout transitions `status` to `PAID` and adds the effective sales (`gross_sales_cents` minus `returned_sales_cents`) to the streamer's `lifetime_gmv_cents`, which in turn re-triggers the depth-3 tier-recompute and suspension reconciliation cascade. Two admins racing to pay out the same settlement serialize first-writer-wins on the settlement's `status`; the loser receives `ERR_INVALID_STATE`.

### 3.9. Violations, Penalties, and Appeals

A reviewer (operations or compliance) records a violation against a streamer with a `streamer_id`, an optional `application_id`, a `violation_type` from `FALSE_ADVERTISING`, `WRONG_PRODUCT`, `VIOLATING_CONTENT`, or `DATA_FRAUD`, and an array of `evidence_refs` (URIs or content-moderation event ids). The server then runs the penalty calculation to populate `severity`, `penalty_action`, `fine_cents`, and `suspension_days`, and writes the violation in `status` `OPEN` with `enforced_at` null.

The penalty calculation begins with the per-type severity floor: 2 for `FALSE_ADVERTISING`, 1 for `WRONG_PRODUCT`, 3 for `VIOLATING_CONTENT`, 4 for `DATA_FRAUD`. An evidence bonus of 1 is added when the number of items in `evidence_refs` is at least 3; otherwise the bonus is 0. The sum is the `severity` score. The penalty action is then chosen by comparing the streamer's `violation_score` plus the new severity against thresholds, with one additional bypass clause: if the post-violation score reaches 100 or the violation is `DATA_FRAUD` with severity at least 4, the penalty is `BLACKLIST`; otherwise, if the post-violation score reaches 50 or the severity is at least 4, the penalty is `SUSPENSION` with `suspension_days` 30; otherwise, if the severity is at least 2, the penalty is `FINE` with `fine_cents` equal to the severity multiplied by 50,000; otherwise the penalty is `WARNING`.

The violation sits in `status` `OPEN` while it is appealable. A streamer may file an `Appeal` against their own violation up to 7 days after the violation's `created_at`; attempting to file after the window yields `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422). The appeal carries the streamer's `argument`, pins the targeted `violation_id`, and is recorded with `decision` `PENDING` and `decided_at` null; the violation transitions from `OPEN` to `APPEAL_PENDING`. The `streamer_id` on the appeal mirrors the violation's `streamer_id` for ownership-check purposes.

A `ComplianceReviewer` decides the appeal by supplying a `decision` of `OVERTURN` or `UPHOLD`. An `OVERTURN` decision sets the appeal's `decision` to `OVERTURNED` and `decided_at` to the current logical clock, transitions the violation from `APPEAL_PENDING` to `OVERTURNED`, and runs a depth-3 cascade: if the streamer was `SUSPENDED` or `BLACKLISTED` solely because of this violation, the streamer's `status` reverts to `ACTIVE` and `suspension_until` is set to null; the violation's `severity` is subtracted from the streamer's `violation_score`; and the streamer's `tier` is recomputed against the new `violation_score`. If the violation had carried a fine that was already paid, the cascade emits a payment-refund event recorded on `AuditLog`. An `UPHOLD` decision sets the appeal's `decision` to `UPHELD`, transitions the violation to `UPHELD`, and the system auto-transitions the violation from `UPHELD` to `ENFORCED` immediately afterward without further mutation. Two appeal-decide actions racing on the same violation serialize first-writer-wins on the violation's `status`; the loser receives `ERR_INVALID_STATE`.

When neither an appeal is filed nor an overturn decided within 7 days of the violation's `created_at`, the periodic sweep takes over. For each `OPEN` violation whose `created_at` plus 7 days is at or before the logical clock, with no `Appeal` on record, the sweep transitions the violation to `ENFORCED`, records `enforced_at` as the current logical clock, and applies the `penalty_action`: `WARNING` has no streamer-state effect; `FINE` increments the streamer's `violation_score` by the violation's `severity` and the fine is charged externally through a payment event; `SUSPENSION` sets the streamer's `status` to `SUSPENDED` and `suspension_until` to the current logical clock plus `suspension_days`; `BLACKLIST` sets the streamer's `status` to `BLACKLISTED` and leaves `suspension_until` null. A `SUSPENSION` or `BLACKLIST` enforcement also cascades depth-3 through every future `SCHEDULED` application of the streamer: each such application is auto-cancelled, the refund calculation runs against its invoice, and the product associations are released.

### 3.10. The Sweep, the Clock, and External Event Streams

A periodic sweep, callable only by a `PlatformAdmin`, advances three time-driven processes in a single pass. For every `CommissionSettlement` in `status` `WINDOW_OPEN` whose `return_window_ends_at` is at or before the logical clock, the sweep runs the final commission variant and moves the settlement to `READY_FOR_PAYOUT` or `REVERSED` depending on whether `final_payout_cents` is non-negative or negative. For every `Violation` in `status` `OPEN` whose `created_at` plus 7 days is at or before the logical clock and which has no `Appeal`, the sweep applies the penalty cascade described above. For every `Streamer` whose `status` is `SUSPENDED` and whose `suspension_until` is at or before the logical clock, the sweep returns the streamer's `status` to `ACTIVE` and clears `suspension_until`.

The platform consumes events from four external systems. A payment event carries `source` `PAYMENT` and a `kind` of either `DEPOSIT_PAID` or `DEPOSIT_REFUNDED`; the `DEPOSIT_PAID` event drives the invoice transition from `ISSUED` to `DEPOSIT_PAID` and sets the application's `deposit_paid` to true. An e-commerce event carries `source` `ECOMMERCE` with `kind` `BROADCAST_GMV` or `RETURN_REPORTED`; sales accumulate into the settlement's `gross_sales_cents` and returns into `returned_sales_cents` only when the event's `occurred_at` is at or before the settlement's `return_window_ends_at`. A content-moderation event carries `source` `CONTENT_MOD` and `kind` `CONTENT_FLAGGED`; the system auto-creates a `Violation` of `violation_type` `VIOLATING_CONTENT` against the targeted streamer with the event identifier in `evidence_refs`. An IM event carries `source` `IM` and `kind` `IM_CHANNEL_OPENED`; the system writes an `AuditLog` entry and makes no further state change. Every injected event is persisted with its `application_id`, `streamer_id`, `amount_cents`, and `occurred_at` (and the chosen `source`/`kind`).

### 3.11. Audit Trail

Every state-changing action emits an `AuditLog` row. The row captures the `subject_kind` (`SCHEDULE_APPLICATION`, `VIOLATION`, `STREAMER`, or `INVOICE`), the `subject_id`, an `action` label (one of `SUBMIT`, `OPS_APPROVE`, `COMPLIANCE_APPROVE`, `REJECT`, `CANCEL`, `PENALTY_ENFORCED`, `APPEAL_DECIDED`, `REFUND_ISSUED`), the `actor_role` and `actor_id` (mirroring `X-User-Role` and `X-User-ID`), the `from_state` and `to_state` (each nullable when the action does not move a state machine), and a `payload_snapshot` object recording the salient fields after the action.

## 4. Endpoint Definitions

All endpoint paths are mounted under `/live-schedule`. Endpoints that create a new resource respond with HTTP 201 on success; endpoints that read or modify an existing resource (including state-transition action endpoints) respond with HTTP 200. Error responses follow §2.2 and use the catalogue in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /live-schedule/streamers | Create a streamer profile | PlatformAdmin |
| GET | /live-schedule/streamers/{id} | Read a streamer profile | PlatformAdmin, OperationsReviewer, ComplianceReviewer, Streamer (own only) |
| GET | /live-schedule/streamers | List streamers (paginated, filterable by `status`, `tier`) | PlatformAdmin, OperationsReviewer, ComplianceReviewer |
| POST | /live-schedule/studios | Create a studio | PlatformAdmin |
| PATCH | /live-schedule/studios/{id} | Update studio `status`/`capacity` (OCC `version`) | PlatformAdmin |
| POST | /live-schedule/studios/{studio_id}/time-slots | Add an AVAILABLE or MAINTENANCE time-slot configuration | PlatformAdmin |
| GET | /live-schedule/studios/{studio_id}/time-slots | List a studio's time-slot configurations | PlatformAdmin, OperationsReviewer, Streamer |
| POST | /live-schedule/products | Onboard a product | PlatformAdmin |
| PATCH | /live-schedule/products/{id} | Update product `status`/`available_stock` (OCC `version`) | PlatformAdmin |
| POST | /live-schedule/applications | Create a draft application | Streamer |
| GET | /live-schedule/applications/{id} | Read an application with computed fees | PlatformAdmin, OperationsReviewer, ComplianceReviewer, Streamer (own only) |
| GET | /live-schedule/applications | List applications (filter by `streamer_id`, `studio_id`, `review_status`, `operational_status`) | PlatformAdmin, OperationsReviewer, ComplianceReviewer, Streamer (own only) |
| POST | /live-schedule/applications/{id}/products | Associate a product with an application (pre-approval and during-broadcast) | Streamer |
| POST | /live-schedule/applications/{id}/submit | Submit a draft application for ops review | Streamer |
| POST | /live-schedule/applications/{id}/ops-approve | Operations review decision (carries `decision`, optional `reason`) | OperationsReviewer |
| POST | /live-schedule/applications/{id}/compliance-approve | Compliance review decision (carries `decision`, optional `reason`, optional `version`) | ComplianceReviewer |
| POST | /live-schedule/applications/{id}/withdraw | Streamer withdraws own application from DRAFT or OPS_PENDING | Streamer |
| POST | /live-schedule/applications/{id}/start-live | Begin broadcast | Streamer |
| POST | /live-schedule/applications/{id}/end-live | End broadcast | Streamer |
| POST | /live-schedule/applications/{id}/cancel | Cancel a SCHEDULED application before start (carries `reason`) | Streamer, OperationsReviewer |
| POST | /live-schedule/applications/{id}/force-cancel | Force-cancel a LIVE application (carries `reason`) | OperationsReviewer |
| GET | /live-schedule/applications/{id}/approvals | List approval records for an application | PlatformAdmin, OperationsReviewer, ComplianceReviewer, Streamer (own only) |
| GET | /live-schedule/applications/{id}/invoice | Read the slot-fee invoice for an application | PlatformAdmin, OperationsReviewer, ComplianceReviewer, Streamer (own only) |
| GET | /live-schedule/applications/{id}/settlement | Read the commission settlement for an application | PlatformAdmin, OperationsReviewer, ComplianceReviewer, Streamer (own only) |
| POST | /live-schedule/settlements/{id}/payout | Pay out a READY_FOR_PAYOUT settlement | PlatformAdmin |
| POST | /live-schedule/violations | Create a violation record | OperationsReviewer, ComplianceReviewer |
| POST | /live-schedule/violations/{id}/appeal | Streamer files an appeal (carries `argument`) | Streamer |
| POST | /live-schedule/appeals/{id}/decide | Compliance decides an appeal (carries `decision`) | ComplianceReviewer |
| GET | /live-schedule/violations | List violations (filter by `streamer_id`, `status`) | PlatformAdmin, OperationsReviewer, ComplianceReviewer, Streamer (own only) |
| GET | /live-schedule/audit-logs | Query the audit log (filter by `subject_kind`, `subject_id`, `actor_role`) | PlatformAdmin, ComplianceReviewer |
| POST | /live-schedule/_clock/advance | Test-only: advance the simulated clock to a supplied `to` ISO 8601 timestamp | PlatformAdmin |
| GET | /live-schedule/_clock/now | Test-only: read the current simulated clock | PlatformAdmin, OperationsReviewer, ComplianceReviewer, Streamer |
| POST | /live-schedule/_sweep/run | Run the periodic sweep | PlatformAdmin |
| POST | /live-schedule/_events/emit | Inject an external-system event (`source`, `kind`, optional `application_id`, optional `streamer_id`, optional `amount_cents`, `occurred_at`) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_STUDIO_INTERVAL_CONFLICT | 409 |
| ERR_STOCK_INSUFFICIENT | 409 |
| ERR_OUT_OF_AVAILABLE_WINDOW | 409 |
| ERR_TOO_LATE_TO_CANCEL | 409 |
| ERR_INVALID_INTERVAL | 422 |
| ERR_QUALIFICATION_MISSING | 422 |
| ERR_PRODUCT_CERT_MISSING | 422 |
| ERR_PRODUCT_CATEGORY_MISMATCH | 422 |
| ERR_PRODUCT_NOT_ON_SHELF | 422 |
| ERR_LIVE_ASSOCIATION_DENIED | 422 |
| ERR_STREAMER_NOT_ACTIVE | 403 |
| ERR_STREAMER_BLOCKED | 422 |
| ERR_DEPOSIT_UNPAID | 422 |
| ERR_APPEAL_WINDOW_CLOSED | 422 |
| ERR_REASON_REQUIRED | 422 |
| ERR_PAGINATION_INVALID | 400 |
| ERR_VALIDATION_FAILED | 422 |
