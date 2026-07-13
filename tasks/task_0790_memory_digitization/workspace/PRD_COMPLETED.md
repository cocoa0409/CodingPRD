# Memory Digitization API — Product Requirements Document

## 1. Introduction

Families accumulate decades of memories on media formats that quietly decay in closets and attics: aging videotapes, brittle film reels, loose photographs, and audio cassettes. This document specifies the backend service for a memory-preservation and media-digitization business modeled on operations such as Legacybox. The service manages the full journey of a customer's keepsakes — from the moment an order is quoted and a shipping kit is released, through physical intake and barcode-tracked storage, into a machine-scheduled digitization pipeline with quality-control review, and finally out to a cloud, USB, or DVD deliverable the customer can retrieve.

The platform must reconcile two concerns that evolve on their own timelines: the **fulfillment** of a customer's physical media and the **payment** for the work. An order is priced from customer-declared media counts at the time it is placed, but the final billable amount may shift if items are lost or damaged in transit and written off after adjudication. Rush turnaround, an optional lost-and-damage protection add-on, volume discounts, and a single recognized promotional code all feed the quote. Because a single deliverable is generated only once an order's entire pipeline has resolved, and because a regenerated deliverable supersedes an earlier one, the system also guards against a client acting on a stale view of an order.

This specification is the sole contract for the implementation. It defines the resource model, the parallel state machines that drive an order and its media through their lifecycles, the pricing and payout calculations to the cent, the validation ordering that decides which error a rejected request receives, and the role-based permissions that separate the customer, the intake dock, the lab, and the claims desk.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an identifier for the acting user, and `X-User-Role`, the caller's operational role. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `Customer`, `IntakeTech`, `LabTech`, `ClaimsAdjuster`, and `Admin`.

- A `Customer` is the end customer who places orders, authorizes payment, downloads deliverables, and files claims. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a `Customer` compare the resource's owning-customer foreign key to `X-User-ID`: a `Customer` may act on an `Order` (or an `OutputArtifact` belonging to that order) only when the order's `customer_id` equals `X-User-ID`. A violation is rejected with `ERR_NOT_OWNER` (HTTP 403). The same ownership rule applies when a `Customer` places an order — the supplied `customer_id` must equal `X-User-ID`, else `ERR_NOT_OWNER` — and when a `Customer` reads a `Customer` record, which is permitted only for their own record (the path `id` must equal `X-User-ID`, else `ERR_NOT_OWNER`).
- An `IntakeTech` is the receiving-dock operator who marks orders as received and logs physical media items into storage bins.
- A `LabTech` is the lab operator who builds batches, runs digitization, performs QC and rescans, and generates deliverables.
- A `ClaimsAdjuster` adjudicates lost-and-damage claims.
- An `Admin` is a superset operator who may perform any business operation of the other roles and additionally configures machines, storage bins, customers, and the logical clock.

For `IntakeTech`, `LabTech`, `ClaimsAdjuster`, and `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. Ownership enforcement applies only to the `Customer` role.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock (§2.6).
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by `created_at` in ascending order. Beyond pagination, list endpoints accept optional equality filters supplied as query parameters: `/orders` by `customer_id`, `fulfillment_status`, and `payment_status`; `/media-items` by `order_id`, `batch_id`, `bin_id`, and `status`; and `/batches` by `machine_id` and `status`. Additionally, when a `Customer` lists `/orders`, the result is implicitly restricted to orders whose `customer_id` equals the caller, in addition to any supplied filter.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of records matching the filter before pagination and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Most resources in the system are top-level entities that carry a standard set of system-managed fields: `Customer`, `Order`, `Machine`, `StorageBin`, `Batch`, `MediaItem`, `OutputArtifact`, and `DamageClaim`.

- `id` — a unique, server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation. It underpins the optimistic-concurrency mechanism described in §2.7.

Two resources are lightweight audit records and do **not** carry the full set: a `QCReview` and a `DownloadEvent` each carry only an `id` and a `created_at`. They have neither an `updated_at` nor a `version` field, because they are immutable once written.

Whenever a derived or counter field on a resource changes as a side effect of an operation — for example, a `Customer`'s `wallet_credit_cents`, or an `Order`'s `written_off_count` — that change is a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented. Where a state transition is described as advancing an order or bumping a count on an order, treat it as one such mutation.

### 2.5. Monetary Values, Counts, and Precision

All monetary amounts are stored and returned as integer numbers of cents; there are no fractional cents. Where a calculation multiplies a monetary amount by a percentage — the volume discount, the rush surcharge, and the percentage portion of the protection fee — the product is rounded to a whole number of cents using the round-half-up rule (a value with a fractional part of exactly one-half rounds up to the next cent). The risk score is an integer constrained to the range from 0 through 100 inclusive. All declared counts and computed counts are non-negative integers.

### 2.6. The Logical Clock

Time in this system is governed by a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any client sets it the clock returns this default and never falls back to real-world time. An administrative capability sets the current clock instant to a supplied ISO 8601 value provided as `to_iso8601`. Every timestamp the system derives — a media item's `stored_at`, an artifact's `expires_at`, a download's `downloaded_at`, and every retention or claim-window comparison — reads from this logical clock.

### 2.7. Optimistic Concurrency on Deliverable Generation

Generating a deliverable for an order is guarded by optimistic concurrency control. The generate-deliverable operation requires the caller to submit `expected_order_version`, carrying the `version` of the target `Order` that the client last observed. If `expected_order_version` does not equal the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). This protects against a client generating a deliverable from a stale view: because a prior generation — or a restore/regeneration, which legitimately supersedes an earlier deliverable — has already advanced the order's `version`, a caller holding the earlier version number is working from an out-of-date picture of the order and is refused. No other endpoint requires a version field; only deliverable generation carries this check.

### 2.8. Nested Resource Retrieval and Referential Validation

Several read endpoints expose a resource nested under a parent path (for example, an order's deliverables, a media item's QC reviews, or a media item's claims). For any path that contains a resource identifier, the identifier is validated left to right: the first identifier in the path that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404), before any deeper identifier or business rule is considered.

Separately, when a request body names a foreign key — a `customer_id`, `machine_id`, `bin_id`, `media_item_id`, or `order_id` — that reference must resolve to an existing row. An unresolved body reference is rejected with `ERR_NOT_FOUND` (HTTP 404). This body-reference check applies when creating an order, logging a media item into an order, creating a batch, loading a media item into a batch, and filing a damage claim.

### 2.9. Validation Ordering and Precedence

When more than one rule could reject a request, the checks are evaluated in a fixed precedence so that the returned `error_id` is deterministic. The global order is:

1. **Authentication** — headers present and role recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for the endpoint, else `ERR_UNAUTHORIZED` (403).
3. **Path existence** — each path identifier resolves, left to right, else `ERR_NOT_FOUND` (404).
4. **Body foreign-key existence** — body references resolve, else `ERR_NOT_FOUND` (404).
5. **Ownership** — a `Customer` acting on an order or its artifacts owns it, else `ERR_NOT_OWNER` (403).
6. **State and business rules** — the entity is in the required state for the transition and all domain-specific preconditions hold; these are described in §3 with their individual error codes.
7. **Body field validity** — required fields are present with valid enums and types, else `ERR_VALIDATION` (400); and a supplied `promo_code` other than the single recognized code is rejected with `ERR_INVALID_PROMO` (422).

Within the state-and-business tier, a request that targets an entity in the wrong state for a requested transition is rejected with the generic `ERR_INVALID_STATE` (HTTP 409) unless a more specific rule below claims it. Where several domain rules apply to one endpoint, the more foundational readiness checks are evaluated ahead of the more specific ones — for example, on deliverable generation the order-readiness check precedes the payment-capture check, which in turn precedes the stale-version check. The specific orderings are called out in the workflow narratives of §3.

## 3. Business Logic & Workflows

### 3.1. Placing an Order and Computing the Estimate

A `Customer` places an order for themselves (an `Admin` may also place one on a customer's behalf). The order names the ordering customer through its `customer_id` and records the chosen service plan tier in `plan_tier`, which is one of `STANDARD_KIT`, `FAMILY_KIT`, or `CLOSET_KIT`. The customer chooses a `turnaround` of either `STANDARD` or `RUSH`, and a default delivery medium in `output_option` of `CLOUD`, `USB`, or `DVD`. Two optional add-on flags are captured: `lost_damage_protection`, indicating whether the paid protection add-on was purchased (defaulting to not purchased), and `is_gift`, indicating whether the order is a gift (defaulting to not a gift). When the order is a gift, `gift_recipient_email` holds the recipient's address; the field is never required and is stored exactly as supplied (or absent when the client omits it) — it is neither enforced when `is_gift` is true nor cleared when `is_gift` is false. An optional `promo_code` may be supplied.

At creation the customer declares how many items of each media type they are sending, through `declared_tape_count`, `declared_film_count`, `declared_photo_count`, and `declared_audio_count`; each declared count defaults to zero when omitted. From these four declared counts the system computes an **estimate** and stores it in `estimate_total_cents`. A freshly created order begins with `fulfillment_status` of `QUOTED` and `payment_status` of `UNPAID`. Its `final_total_cents` is absent until the first final recompute occurs, its `captured_total_cents` is zero, its `refunded_total_cents` is zero, its `received_item_count` is zero, and its `written_off_count` is zero.

The estimate is computed in two stages, both working in integer cents. The first stage produces a discounted subtotal. Each media type contributes a per-item line rate: 1200 cents per tape, 1500 cents per film reel, 50 cents per photo, and 1000 cents per audio item. The raw subtotal is the sum of each media type's count multiplied by its rate. The total item count is the sum of the four counts. A volume-discount percentage is then selected from the item count: when the item count is at least 40 the percentage is twenty percent; otherwise when the item count is at least 20 the percentage is ten percent; otherwise there is no volume discount. The volume discount amount is the raw subtotal multiplied by that percentage, rounded half up to whole cents, and the discounted subtotal is the raw subtotal minus that discount amount.

The second stage turns the discounted subtotal into the order total by layering fees and then a promotional reduction, strictly in this order. First, a rush surcharge applies only when `turnaround` is `RUSH`: it is the discounted subtotal multiplied by thirty percent, rounded half up to whole cents; for `STANDARD` turnaround the surcharge is zero. Second, a protection fee applies only when `lost_damage_protection` was purchased: it is a flat 1500 cents plus two percent of the discounted subtotal (that percentage portion rounded half up to whole cents); with no protection the fee is zero. Third, a pre-discount total is formed as the discounted subtotal plus the rush surcharge plus the protection fee — this pre-discount total must be computed before any promotional reduction. Fourth, the promotional reduction is selected from the pre-discount total, not from the subtotal: only the code `SAVE5` is recognized, and when it is present the reduction is 1000 cents if the pre-discount total is at least 13000 cents, or 500 cents if the pre-discount total is at least 10000 cents but below that, or zero otherwise; with no recognized code the reduction is zero. The order total is the pre-discount total minus the promotional reduction. At order creation this total is the estimate stored in `estimate_total_cents`.

A `promo_code` that is present but is anything other than `SAVE5` causes the order creation to be rejected with `ERR_INVALID_PROMO` (HTTP 422). Missing required fields, or an invalid enum or type on any field, are rejected with `ERR_VALIDATION` (HTTP 400).

### 3.2. Authorizing and Capturing Payment

An order advances along two independent axes that never block each other except where deliverable generation reads both. The fulfillment axis moves `QUOTED → AWAITING_MEDIA → RECEIVED → PROCESSING → READY`. The payment axis moves `UNPAID → AUTHORIZED → CAPTURED` and may later branch to `PARTIALLY_REFUNDED`.

The customer authorizes payment as the opening move, which both authorizes the charge and releases the shipping kit. Authorizing is permitted only when the order's `fulfillment_status` is `QUOTED` and its `payment_status` is `UNPAID`; in a single call it advances `payment_status` from `UNPAID` to `AUTHORIZED` and `fulfillment_status` from `QUOTED` to `AWAITING_MEDIA`. This is the one transition that moves both axes at once, and it increments the order's `version`. Attempting it from any other state is rejected with `ERR_INVALID_STATE` (409).

An `Admin` later captures the authorized payment. Capture is permitted only when `payment_status` is `AUTHORIZED`; it advances `payment_status` from `AUTHORIZED` to `CAPTURED` and, at that moment, records `captured_total_cents` as equal to the order's `estimate_total_cents`. Capture is purely a payment-axis move and does not touch `fulfillment_status`. It increments the order's `version`.

### 3.3. Intake: Receiving Media and Storing Items

Once the customer's package arrives, an `IntakeTech` marks the media as received. Marking an order received is permitted only when its `fulfillment_status` is `AWAITING_MEDIA` and its `payment_status` is one of `AUTHORIZED` or `CAPTURED`; it advances `fulfillment_status` from `AWAITING_MEDIA` to `RECEIVED` and increments the order's `version`.

With the order in `RECEIVED`, the `IntakeTech` logs each physical item. Logging requires the order's `fulfillment_status` to be `RECEIVED`; if it is not, intake is rejected with `ERR_ORDER_NOT_RECEIVED` (HTTP 409). Each logged item records its `media_type` — one of `TAPE`, `FILM`, `PHOTO`, or `AUDIO` — is placed into a storage bin identified by `bin_id`, and may carry a `barcode`, which is unique when provided and absent otherwise; a `barcode` that duplicates an existing one is rejected with `ERR_VALIDATION` (HTTP 400). A new item begins in `LOGGED` status with `qc_attempts` of zero, no `batch_id` yet, no captured `digitized_minutes` and no `page_count` yet. Its `stored_at` is set to the current logical clock instant, and its retention window ends at `retention_until`, which is `stored_at` plus 30 days and is the exclusive end of the bin-occupancy window. Logging an item increments the owning order's `received_item_count` by one and increments the order's `version`.

A storage bin is created by an `Admin` with a physical `label` and a `capacity`, where the capacity is an integer of at least 1 and expresses the maximum number of media items whose retention windows may overlap in that bin at once. Assigning a media item to a bin must not push the number of overlapping retention windows in that bin above its `capacity`: treating each item's occupancy as the half-open interval from its `stored_at` up to but not including its `retention_until`, if admitting the new item would make the count of mutually overlapping windows exceed the bin's capacity, the intake is rejected with `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409).

### 3.4. Batching and Running Digitization

Digitization work is organized on machines. An `Admin` registers a `Machine` (a digitization station) with a `name`, a `kind` — one of `TAPE_DECK`, `FILM_SCANNER`, `PHOTO_SCANNER`, or `AUDIO_DECK` — and an informational `capacity` (the maximum media items per batch on that machine, defaulting to 50).

A `LabTech` schedules a `Batch` against a machine by naming its `machine_id` and a reservation window from `scheduled_start` (inclusive) to `scheduled_end` (exclusive), where `scheduled_end` must be strictly after `scheduled_start`. A batch may also carry a `capacity` for the maximum media items it holds (defaulting to 50). The reservation window is half-open: a new batch's window must not overlap any existing batch's window on the same machine, though two windows that merely touch at an endpoint (one ends exactly where the next begins) are allowed. An overlapping reservation is rejected with `ERR_MACHINE_DOUBLE_BOOKED` (HTTP 409). A newly created batch begins in `OPEN` status with a `loaded_count` of zero.

Loading places a `LOGGED` media item into a batch. Loading is permitted only when the item's `status` is `LOGGED`, the batch's `status` is `OPEN` or `LOADED`, and the batch's `loaded_count` is below its `capacity`. Loading advances the item from `LOGGED` to `PREPPED`, sets the item's `batch_id` to that batch, increments the batch's `loaded_count` by one, and sets the batch's `status` to `LOADED`.

Running the batch starts scanning. A run is permitted only when the batch's `status` is `LOADED` and its `loaded_count` is at least 1. Running advances the batch from `LOADED` to `RUNNING` and, for each loaded media item, advances that item from `PREPPED` to `SCANNING`. A cross-entity gate protects this step: a media item may begin scanning only when its owning order's `fulfillment_status` is `RECEIVED` or `PROCESSING`; if the gate is not met the run is rejected with `ERR_ORDER_NOT_RECEIVED` (HTTP 409). As a running batch drives its first item into `SCANNING`, the owning order bubbles up: any order whose `fulfillment_status` is `RECEIVED` advances to `PROCESSING`. A batch later advances on its own from `RUNNING` to `COMPLETED` once every loaded item has left `SCANNING` (reached `QC_PENDING` or beyond). The system also reserves a `FAILED` batch state and a `FAILED → OPEN` reopen path for aborted runs; these are internal and are not driven by any public endpoint in this service.

### 3.5. Scan Completion, Quality Control, and the Rescan Loop

When scanning finishes, a `LabTech` completes the scan, advancing the item from `SCANNING` to `QC_PENDING`. At this point the runtime or extent captured during the scan is recorded: `digitized_minutes` holds the captured runtime for tape, film, or audio items, and `page_count` holds the page or frame count for photo items. Both fields are optional on the complete-scan request and remain absent when omitted; a supplied `digitized_minutes` may be any number and a supplied `page_count` must be an integer.

A `LabTech` then renders a QC decision on a `QC_PENDING` item, supplying a `decision` of either `PASS` or `FAIL` and optional `notes`. Every decision increments the item's `qc_attempts` by one and writes an immutable `QCReview` record. That review carries its `media_item_id`, the `decision`, the reviewer's `notes`, and an `attempt_number` equal to the item's `qc_attempts` after the increment (the 1-based ordinal of this review). A `PASS` advances the item from `QC_PENDING` to `OUTPUT_READY` and then re-evaluates whether the owning order may reach `READY` (see §3.6). A `FAIL` always lands the item in `QC_FAIL`, regardless of how many attempts remain.

A failed item may be sent back to scanning. Rescanning is permitted only when the item's `status` is `QC_FAIL` and its `qc_attempts` is below the maximum of 3 attempts; it returns the item from `QC_FAIL` to `SCANNING` so it can be scanned and reviewed again. Once an item has accumulated 3 QC attempts, a further rescan is refused with `ERR_QC_ATTEMPTS_EXCEEDED` (HTTP 409) and the item remains in `QC_FAIL` — the attempt cap, not an automatic write-off, enforces the limit, and such an item is resolved later through a lost-and-damage claim. A media item's QC reviews can be listed in attempt order for audit.

### 3.6. Reaching Ready and Generating the Deliverable

An order reaches the end of its fulfillment axis once its media has all resolved. The system advances an order from `PROCESSING` to `READY` when every media item belonging to that order is in either `OUTPUT_READY` or `WRITTEN_OFF` status and at least one of them is `OUTPUT_READY`. This is a bubble-up transition evaluated after each QC pass and after each write-off; it gates deliverable generation.

Generating a deliverable produces an `OutputArtifact` for the order. Three preconditions are checked, in this order. First, the order's `fulfillment_status` must be `READY`; otherwise the request is rejected with `ERR_ORDER_NOT_READY` (HTTP 409). Second, the order's `payment_status` must be `CAPTURED`; otherwise the request is rejected with `ERR_PAYMENT_NOT_CAPTURED` (HTTP 402). Third, the submitted `expected_order_version` must equal the order's current `version` per the concurrency rule in §2.7; otherwise it is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). The caller also supplies the deliverable's `output_type`, one of `CLOUD`, `USB`, or `DVD`.

A generated artifact begins in `AVAILABLE` status. The system mints a `download_token` for it, sets its `download_count` to zero, records an `item_count_snapshot` equal to the number of `OUTPUT_READY` media items included at generation time, and sets its `expires_at` to the artifact's `created_at` plus 30 days. Generating a new artifact for an order supersedes any prior deliverable: any existing `AVAILABLE` artifact of that order is moved to `REVOKED`. This regeneration path is how a customer restores or re-obtains a deliverable, and because generation increments the order's `version`, a subsequent generation from a stale version number is caught by the concurrency check above.

A customer retrieves a `CLOUD` deliverable by downloading it. A download is permitted only when the artifact's `output_type` is `CLOUD`; a download attempt on a `USB` or `DVD` artifact is rejected with `ERR_NOT_DOWNLOADABLE` (HTTP 409). The download is allowed only while the logical clock is strictly before the artifact's `expires_at`; if the clock has reached or passed `expires_at`, the download is refused with `ERR_DOWNLOAD_EXPIRED` (HTTP 409) and the artifact is lazily moved from `AVAILABLE` to `EXPIRED` at that moment. The download is also allowed only while `download_count` is below the limit of 3 downloads per artifact; a further attempt is refused with `ERR_DOWNLOAD_LIMIT_REACHED` (HTTP 409). A successful download increments the artifact's `download_count` by one and records an immutable `DownloadEvent` carrying its `output_artifact_id`, a `sequence_number` equal to the new download count (its 1-based ordinal against the artifact), and a `downloaded_at` set to the current logical clock instant. An artifact's download events can be listed for audit.

### 3.7. Lost-and-Damage Claims and the Refund Cascade

If a customer's item is lost or damaged, a claim may be filed against it. A claim names the `order_id` it is filed against and the `media_item_id` of the affected item, and that media item must belong to the named order — its `order_id` must match the claim's `order_id`; a mismatch is rejected with `ERR_MEDIA_NOT_IN_ORDER` (HTTP 422). The claim records a `claim_type` of either `LOST` or `DAMAGED` and an optional `declared_value_cents` (the customer's declared sentimental or replacement value, which policy will cap). A claim must be filed within 90 days of the order's transition to `READY`: if the logical clock is later than the order's ready instant plus 90 days, the filing is rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422). This window is enforced only after the order has reached `READY`; a claim filed against an order that has not yet reached `READY` is accepted without any time gate, regardless of its `fulfillment_status`. A filed claim begins in `SUBMITTED` status with a `payout_cents` of zero; filing it increments the owning customer's `pending_claim_count` and recomputes that customer's `risk_score`.

A customer's `risk_score` is an integer capped at 100, computed as 20 points for each of that customer's claims in `APPROVED` status plus 5 points for each claim in `SUBMITTED` or `UNDER_REVIEW` status, with the sum capped at 100. At submission time this score is read provisionally, so the still-open claim contributes its 5-point pending weight; the value persisted to the customer's `risk_score` reflects the counts as they stand whenever a claim settles. The customer's `approved_claim_count` is the number of that customer's claims in `APPROVED` status, and the `pending_claim_count` is the number in `SUBMITTED` or `UNDER_REVIEW` status. A customer also carries a `wallet_credit_cents` balance of refundable store credit and is registered with an `email` (unique and non-empty), a `full_name`, and a two-letter `state_code`. At registration, `email`, `full_name`, and `state_code` are each required to be a non-empty string (the `state_code` length is described but not otherwise validated), and an `email` that is missing, empty, or duplicates an existing customer's is rejected with `ERR_VALIDATION` (HTTP 400).

A `ClaimsAdjuster` adjudicates a `SUBMITTED` claim with a single `decision` of `APPROVE` or `REJECT`, plus optional `notes`. Approval is permitted only when the claim is `SUBMITTED` and the owning order's `payment_status` is `CAPTURED`; if the order's payment is not captured, approval is rejected with `ERR_PAYMENT_NOT_CAPTURED` (HTTP 402). Approving a claim triggers a cascade across four entities:

- The claim's `payout_cents` is computed by policy (below), and the claim advances from `SUBMITTED` to `APPROVED`.
- The affected media item is written off, advancing it to `WRITTEN_OFF`, and the owning order's `written_off_count` is increased by one.
- The order's `refunded_total_cents` is increased by the payout, the order's `payment_status` advances from `CAPTURED` to `PARTIALLY_REFUNDED`, and the order's `final_total_cents` is recomputed as the **final** variant of the order total.
- The owning customer's `wallet_credit_cents` is increased by the payout, the customer's `approved_claim_count` increases by one as the claim joins the approved set (and it correspondingly leaves the pending set), and the customer's `risk_score` is recomputed.

Rejecting a claim advances it from `SUBMITTED` to `REJECTED`, decrements the owning customer's `pending_claim_count` by one, and recomputes that customer's `risk_score`; it produces no payout and no order-level changes.

The payout policy depends on the item's media type and whether protection was purchased. Each media type has a base replacement value: 4000 cents for a tape, 6000 cents for a film reel, 200 cents for a photo, and 3000 cents for an audio item. A declared value is taken from `declared_value_cents` when the customer provided one, and otherwise defaults to the item's base value. When the owning order's `lost_damage_protection` was purchased, the payout honors the declared value up to a cap of 10000 cents — that is, the smaller of the declared value and 10000 cents. When protection was not purchased, liability is limited and the declared value is ignored: the payout is the smaller of the item's base value and 1000 cents.

The **final** order total recomputed after a write-off follows the same two-stage calculation as the estimate in §3.1, but its four media-type counts are drawn from the order's surviving media items rather than the declared counts: each count is the number of that order's media items of the given media type whose `status` is not `WRITTEN_OFF`. Because written-off items drop out of these counts, the final total diverges from the estimate whenever the surviving counts differ from the originally declared counts. The result is persisted to `final_total_cents`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or advance an existing resource, and read operations, return `200 OK`. The administrative clock-set capability also returns `200 OK`. Because rendering a QC decision (`POST /media-items/{id}/qc-review`) writes a new `QCReview` and recording a download (`POST /output-artifacts/{id}/download`) writes a new `DownloadEvent`, each returns `201 Created`; the QC-review response's `data` is the updated media item, while the download response's `data` is the newly created `DownloadEvent`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |
| POST | `/machines` | Create a digitization station | Admin |
| POST | `/storage-bins` | Create a storage bin with an overlap capacity | Admin |
| POST | `/customers` | Register a customer | Admin |
| GET | `/customers/{id}` | Read a customer (wallet, risk score, claim counters) | Admin, Customer |
| POST | `/orders` | Create an order; computes the estimate order total | Customer, Admin |
| GET | `/orders/{id}` | Read an order | Admin, Customer |
| GET | `/orders` | List/filter orders | Admin, Customer |
| POST | `/orders/{id}/authorize-payment` | Authorize payment and release the media kit | Customer, Admin |
| POST | `/orders/{id}/capture-payment` | Capture the authorized payment | Admin |
| POST | `/orders/{id}/receive` | Mark the customer's media as received | IntakeTech, Admin |
| POST | `/orders/{id}/media-items` | Log a media item at intake into a storage bin | IntakeTech, Admin |
| GET | `/media-items/{id}` | Read a media item | Admin, LabTech, IntakeTech, Customer |
| GET | `/media-items` | List/filter media items | Admin, LabTech, IntakeTech, Customer |
| POST | `/batches` | Create a digitization batch reserving a machine window | LabTech, Admin |
| GET | `/batches/{id}` | Read a batch | Admin, LabTech |
| GET | `/batches` | List/filter batches | Admin, LabTech |
| POST | `/batches/{id}/load` | Load a media item into the batch | LabTech, Admin |
| POST | `/batches/{id}/run` | Start the batch; each loaded item begins scanning | LabTech, Admin |
| POST | `/media-items/{id}/complete-scan` | Finish scanning; move item to QC pending | LabTech, Admin |
| POST | `/media-items/{id}/qc-review` | Render a QC decision (PASS/FAIL) | LabTech, Admin |
| GET | `/media-items/{id}/qc-reviews` | List QC reviews for a media item | Admin, LabTech |
| POST | `/media-items/{id}/rescan` | Send a failed item back to scanning | LabTech, Admin |
| POST | `/orders/{id}/output-artifacts` | Generate a deliverable for a ready, captured order | Customer, LabTech, Admin |
| GET | `/orders/{id}/output-artifacts` | List an order's output artifacts | Admin, Customer, LabTech |
| GET | `/output-artifacts/{id}` | Read an output artifact | Admin, Customer, LabTech |
| POST | `/output-artifacts/{id}/download` | Record a CLOUD download | Customer, Admin |
| GET | `/output-artifacts/{id}/downloads` | List download events for an artifact | Admin, Customer, LabTech |
| POST | `/damage-claims` | File a lost/damage claim on a media item | Customer, Admin |
| GET | `/orders/{id}/damage-claims` | List an order's damage claims | Admin, Customer, ClaimsAdjuster |
| GET | `/media-items/{id}/damage-claims` | List a media item's damage claims | Admin, Customer, ClaimsAdjuster |
| POST | `/damage-claims/{id}/review` | Adjudicate a claim (APPROVE/REJECT) | ClaimsAdjuster, Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_NOT_READY` | 409 |
| `ERR_ORDER_NOT_RECEIVED` | 409 |
| `ERR_MEDIA_NOT_IN_ORDER` | 422 |
| `ERR_MACHINE_DOUBLE_BOOKED` | 409 |
| `ERR_BIN_CAPACITY_EXCEEDED` | 409 |
| `ERR_QC_ATTEMPTS_EXCEEDED` | 409 |
| `ERR_CLAIM_WINDOW_CLOSED` | 422 |
| `ERR_NOT_DOWNLOADABLE` | 409 |
| `ERR_DOWNLOAD_EXPIRED` | 409 |
| `ERR_DOWNLOAD_LIMIT_REACHED` | 409 |
| `ERR_PAYMENT_NOT_CAPTURED` | 402 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_PROMO` | 422 |
