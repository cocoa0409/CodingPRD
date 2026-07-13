# Photo-Gift & Print Service API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a photo-gift and print service in the style of a consumer print marketplace. A customer starts from a product **template** — a photobook, greeting card, canvas, or wall calendar — builds a **project** by uploading photos, and lets the service auto-arrange those photos into a printable layout. Before anything is printed, the customer reviews a rendered **proof** and either approves it or sends it back for changes; only an approved design may be ordered. Ordering then unfolds through pricing (finish surcharges, volume discounts, promotional codes, and shipping), payment (by card or by store credit), production, and shipping, with the whole thing repeatable through one-click reordering.

The service earns its complexity in three places. First, pricing is a layered calculation: the per-unit price depends on the chosen finish, the line subtotal depends on a volume-discount tier that grows with quantity, and the order total folds in promotions that must be evaluated in a fixed order and rounded a fixed way. Second, the same priced order is computed twice against subtly different rules — an optimistic **quote** that a customer can request at any time, and a stricter **final placement** that re-validates every promotion and can reject an order the quote happily priced. Third, holiday demand is modeled explicitly: administrators declare **surge windows** that both extend promised turnaround and cap how much work may be scheduled into any single production day, so a payment can be refused when the day is full and that capacity is released again if the order is later cancelled.

Three kinds of actor share the system with strictly non-overlapping responsibilities: end-user **customers**, back-office **catalog administrators** who own the catalog and the clock, and **production operators** who move jobs and shipments through fulfillment. The sections below define the global contract every endpoint obeys (Section 2), the domain workflows and their business rules (Section 3), the endpoint surface (Section 4), and the machine-readable error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are well-formed but the role named in `X-User-Role` is not permitted to invoke the target endpoint (per the authorization column of Section 4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly three roles, spelled precisely as follows:

- **`Customer`** — the end user who designs projects, uploads photos, approves proofs, and places, pays, cancels, and reorders orders, and who curates a personal address book. The `Customer` role is *entity-backed*: when `X-User-Role` is `Customer`, the value of `X-User-ID` is the `id` of the acting `Customer` record. Ownership checks on any resource that ultimately references a customer compare that resource's owning `customer_id` (resolved through its chain — a photo through its project, a proof through its project, and so on) to `X-User-ID`. When a `Customer` acts on a project, photo, proof, order, or address whose owning `customer_id` does not equal `X-User-ID`, the request is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).
- **`CatalogAdmin`** — the operator who provisions customer accounts, manages templates, promotions, promo windows, and surge windows, issues store-credit adjustments, and sets the logical clock. When `X-User-Role` is `CatalogAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`ProductionOperator`** — the fulfillment operator who advances production jobs, creates shipments, and advances shipments. When `X-User-Role` is `ProductionOperator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

Ownership enforcement (`ERR_FORBIDDEN_OWNERSHIP`) applies only to the entity-backed `Customer` role acting on customer-scoped resources; the two opaque operator roles are authorized purely by the role permission matrix.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may be at most 100. The `offset` defaults to 0 and has a minimum of 0. Every list is sorted by `created_at` in ascending order (oldest first) before pagination is applied. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the query before pagination and `has_more` is true when records remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp (ISO 8601 UTC with three fractional digits) fixed at creation. Most resources additionally carry an `updated_at` timestamp (same format), refreshed on every mutation, and an integer `version` that begins at 1 and increments by exactly 1 on each mutation. The `Photo` resource is the sole exception: a photo carries only `id` and `created_at`, and has **no** `updated_at` and **no** `version` field. Photo status changes therefore mutate the parent project's `version` and `updated_at`, not the photo's.

Whenever a rule below says that an operation "bumps the version" or "refreshes `updated_at`" of an entity, it means that entity's integer `version` is incremented by one and its `updated_at` is set to the current logical clock instant. Cascading operations that touch several entities bump the `version` of every entity they mutate.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts are integers denominated in cents; there are no fractional-cent fields. Wherever a calculation multiplies a cents amount by a fractional rate — a volume-discount percentage, a percent-off promotion, or a restocking-fee percentage — the product is converted to a whole number of cents by **rounding half up** (a value exactly at the .5 boundary rounds away from zero to the next cent). Additions and subtractions of cents are exact integer arithmetic and are never re-rounded. Where a total could otherwise go negative, it is floored at zero.

### 2.6. The Logical Clock and Temporal Windows

The service runs on a **logical clock** rather than wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and until a `CatalogAdmin` explicitly sets it, every time-dependent computation uses that default instant — the server never consults real wall-clock time. A `CatalogAdmin` moves the clock by supplying a target instant in the `to_iso8601` field; the response echoes the new `current_utc`. The clock drives promo-window eligibility, surge-window coverage, production scheduling dates, and promised ship dates.

Two kinds of temporal window exist, and they differ in endpoint inclusivity. A **promo window** is a **closed** interval `[starts_at, ends_at]`: a promotion is live at an instant when that instant is at or after `starts_at` and at or before `ends_at`. A **surge window** is a **half-open** interval `[starts_at, ends_at)`: a surge window covers a date when the date is at or after `starts_at` and strictly before `ends_at`. Both window types require `ends_at` to be strictly after `starts_at`.

### 2.7. Optimistic Concurrency Control

Generating a new proof for a project is guarded by optimistic concurrency control. The proof-generation request must include `expected_project_version`, and this field is mandatory for that operation — it carries the project `version` the client last observed. Before the proof is created, the server compares `expected_project_version` to the project's current `version`; if they do not match — because some other write has advanced the project's version since the client last read it — the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) and no proof is created. Because each successful proof generation itself bumps the project version and supersedes the prior proof, a second generate call that still carries the pre-supersede version is a stale write and is rejected on this check. No other endpoint takes a version field; optimistic concurrency applies solely to proof generation.

### 2.8. Resource Resolution and Validation Ordering

Requests are validated in a fixed priority order so that failures are reported deterministically. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_UNAUTHORIZED`). Next, every resource referenced by the path or body must exist; path and body references are resolved **left to right** in their natural nesting order (customer, then template, then project, then proof, then order, then address, then promotion, then production job, then shipment, then surge window), and the first missing reference yields the matching not-found error — `ERR_CUSTOMER_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ADDRESS_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND`, `ERR_PRODUCTION_JOB_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, or `ERR_SURGE_WINDOW_NOT_FOUND` (all HTTP 404). After existence, the entity-backed ownership check runs (`ERR_FORBIDDEN_OWNERSHIP`). Only then is the request body inspected for well-formedness — required fields present, enum values legal, chosen finish within the template's offered set, and quantities positive — with any failure reported as `ERR_VALIDATION` (HTTP 422). Domain-state and business rules described in Section 3 are evaluated after all of the above.

### 2.9. Cascading State Effects and Hierarchical Consistency

Several operations mutate more than one entity atomically within the triggering request; all effects of a single request either all commit or none do. Approving a proof cascades three hops — the proof, then its project, then every placed photo. Cancelling a paid order cascades from the order to its production job and onward to any live shipment, and simultaneously moves money. These cascades are described in full in the relevant workflow subsections of Section 3; the guiding principle is that every entity touched in a cascade has its own `version` bumped and `updated_at` refreshed (except `Photo`, which carries neither), and no intermediate, partially-applied state is ever observable.

## 3. Business Logic & Workflows

### 3.1. Catalog, Accounts, and the Address Book

A `CatalogAdmin` provisions the catalog and the customer base. Creating a customer takes an `email` and a `full_name`; the email must be unique across customers and non-empty. Every new customer starts with a `store_credit_cents` balance of 0. That balance is a non-negative amount in cents and may never fall below zero; it is drawn down when an order is paid with store credit, topped up when a cancelled order is refunded to the wallet, and manually adjusted by an operator. A credit adjustment supplies an `amount_cents` delta and a `reason` string; the delta is added to `store_credit_cents` and may be negative, but the resulting balance is floored at zero rather than going negative, and the customer's `version` is bumped.

Product **templates** are the printable blueprints. A template declares its `product_type` — one of `PHOTOBOOK`, `CARD`, `CANVAS`, or `CALENDAR` — a human-readable `name`, a `surface_count` (book pages, calendar months, or card panels, at least 1), a `base_unit_price_cents` (at least 0), a `production_days` base lead time in calendar days (at least 0), and an `allowed_finishes` array that is a non-empty subset of `MATTE`, `GLOSSY`, `LINEN`, `LAY_FLAT`, and `METAL`. A template also fixes the auto-layout envelope: `min_photos` (at least 1) and `max_photos` (at least `min_photos`), plus a `min_dpi` print-quality floor that defaults to 150 when omitted. A template's `status` is `ACTIVE` at creation and becomes `RETIRED` only when an admin retires it; retiring is permitted only from `ACTIVE`, sets `status` to `RETIRED`, and bumps the template `version`. A `RETIRED` template still serves its existing projects and orders, but no new project may be built on it.

Customers curate an address book. Each address records a `recipient_name`, `line1`, an optional `line2` (which defaults to null), `city`, `region`, `postal_code`, and `country`, all tied to the owning `customer_id`. The very first address a customer creates is automatically marked as the default ship-to by setting `is_default` to true; every subsequently created address has `is_default` set to false. This flag is set by the system on creation and is never accepted from the request body. A customer may list their own addresses.

### 3.2. Designing a Project: Photos and Auto-Layout

A `Customer` opens a design by creating a **project** against a template, supplying the owning `customer_id`, the `template_id`, and a `title`. Project creation is refused with `ERR_TEMPLATE_RETIRED` when the chosen template is `RETIRED`. A fresh project begins in `state` `DRAFT` with `photo_count` and `placed_photo_count` both at 0 and `current_proof_id` null.

Uploading a photo into a project records its `filename`, its `width_px` and `height_px` pixel dimensions (each at least 1), and its effective print `dpi` (at least 1), all associated with the target `project_id`. Each uploaded photo begins with `status` `UPLOADED`. Every upload increments the project's `photo_count` and bumps the project `version`.

**Auto-layout** is the transition that arranges the uploaded photos, moving the project from `DRAFT` to `LAID_OUT`. It is admissible only while the project is in `DRAFT`; attempting it from any other state yields `ERR_INVALID_PROJECT_STATE`. When the project state is valid, the print-quality gate is evaluated first: every uploaded photo must have a `dpi` at least equal to the template's `min_dpi`, and if any single photo falls below that floor the entire request is rejected with `ERR_PHOTO_LOW_RESOLUTION` (individual photos are never partially placed — the layout succeeds or fails as a whole). Only after the resolution gate passes are the count bounds checked, in order: the project's `photo_count` must be at least the template's `min_photos`, else `ERR_INSUFFICIENT_PHOTOS` (the empty-photo-set case is caught here); and `photo_count` must be at most the template's `max_photos`, else `ERR_TOO_MANY_PHOTOS`. When all three gates pass, every photo moves from `UPLOADED` to `PLACED`, the project's `placed_photo_count` is recomputed as the number of photos in `PLACED` or `LOCKED` status, the project `state` becomes `LAID_OUT`, and the project `version` is bumped.

### 3.3. The Proofing Loop

Once a project is laid out, the customer reviews rendered **proofs** in a revision loop. Generating a proof is allowed while the project is in either `LAID_OUT` or `IN_PROOF` state; from any other state the request is rejected with `ERR_INVALID_PROJECT_STATE`. Because generation is optimistic-concurrency guarded, the request must carry `expected_project_version`; after the state check passes, that value is compared against the project's current `version`, and a mismatch yields `ERR_STALE_PROJECT_VERSION` as described in Section 2.7. On success the service creates a new proof in `state` `GENERATED` whose `revision_number` is one greater than the highest revision number previously issued for that project (the first proof is revision 1, tied to its `project_id`). Any prior current proof is marked `SUPERSEDED`, the project's `current_proof_id` is repointed to the new proof, the project `state` is set to `IN_PROOF`, and the project `version` is bumped. Generating a proof while already `IN_PROOF` is a legitimate revision that supersedes the previous proof and loops the project back onto itself in `IN_PROOF`.

From a generated proof the customer chooses one of two outcomes. **Requesting changes** is permitted only when the project is `IN_PROOF` and the target proof is still in `GENERATED` state (otherwise `ERR_PROOF_NOT_PENDING`); an optional `note` may accompany the request. It sets the proof to `CHANGES_REQUESTED`, drives the project back along the revision back-edge from `IN_PROOF` to `DRAFT`, unlocks the design by reverting every photo from `PLACED` back to `UPLOADED`, and bumps the project `version`. **Approving** a proof is permitted only when the project is `IN_PROOF`, the target proof is in `GENERATED` state, and that proof is the project's current proof (its `id` equals the project's `current_proof_id`); a violation of the state precondition is `ERR_PROOF_NOT_PENDING`. Approval is the depth-three cascade of Section 2.9: the proof becomes `APPROVED`, then the project `state` becomes `APPROVED`, then every photo moves from `PLACED` to `LOCKED`, and the project `version` is bumped. A proof may also become `SUPERSEDED` without customer action — that happens automatically to the previous current proof whenever a newer proof is generated on the same project.

### 3.4. Pricing: Quotes, Line Subtotals, Discounts, and Turnaround

A customer may request a **provisional quote** for a project at any time — no approval is required — by supplying a `quantity`, a `finish`, a `ship_method`, and optionally a `ship_address_id` and a set of `promo_codes`. The quote returns `unit_price_cents`, `subtotal_cents`, `discount_cents`, `shipping_cents`, `total_cents`, and an estimated `promised_ship_date`. The identical arithmetic recomputes these figures when an order is actually placed, but under stricter promotion eligibility (Section 3.5).

The **unit price** is the template's `base_unit_price_cents` plus a finish surcharge determined by the chosen `finish`: `MATTE` adds nothing, `GLOSSY` adds 300 cents, `LINEN` adds 700 cents, `LAY_FLAT` adds 1200 cents, and `METAL` adds 2500 cents. The **pre-discount amount** is that unit price multiplied by the `quantity`, computed as an exact integer.

A **volume discount** then applies according to a tier chosen by the total `quantity`, using the highest tier threshold that does not exceed the quantity: an order of at least 1 copy but fewer than 10 earns no discount (0 percent); at least 10 but fewer than 25 earns 5 percent; at least 25 but fewer than 50 earns 12 percent; and 50 or more earns 20 percent. The tier percentage is an average rate applied to the whole pre-discount amount: the volume-discount amount is the pre-discount amount multiplied by the tier percentage, rounded half up to whole cents. The `subtotal_cents` is the pre-discount amount minus that volume-discount amount.

**Promotions** are then applied to that subtotal to produce `discount_cents`, and the evaluation is deliberately pinned in both order and rounding. First, the applicable promotions are selected (the eligibility rules differ between quote and placement — see Section 3.5). The applicable set is then sorted by kind, with all `PERCENT` promotions first, then all `FLAT` promotions, then all `FREE_SHIP` promotions, and within a single kind by the promotion's `created_at` ascending. For each promotion, a raw discount is computed against the **original** `subtotal_cents` — never against a running, progressively reduced balance: a `PERCENT` promotion's raw discount is the subtotal multiplied by its `value` divided by 100; a `FLAT` promotion's raw discount is its `value` in cents; and a `FREE_SHIP` promotion contributes a raw discount of 0 (its effect is realized in shipping instead). Each promotion's raw discount is individually rounded half up to whole cents **before** any summing — the individual rounded discounts are then summed, and this per-promo-then-sum ordering is mandatory because summing first and rounding once would yield a different number of cents. Finally, `discount_cents` is the smaller of that sum and the subtotal, so the discount can never exceed the subtotal.

**Shipping** starts from a base charge determined by `ship_method`: 799 cents for `STANDARD` and 1999 cents for `EXPRESS`. If any applicable promotion is of kind `FREE_SHIP`, the `shipping_cents` is 0; otherwise it equals the base charge. The `total_cents` is the subtotal minus the discount plus the shipping, floored at 0.

The **promised ship date** is calendar-day arithmetic over the logical clock date. Transit adds 5 calendar days for `STANDARD` and 2 for `EXPRESS`. Starting from the clock date, the promised date is that date plus the template's `production_days`, plus any surge extension, plus the transit days for the chosen method. In a **quote**, the surge extension is always 0 — the estimate ignores holiday surge entirely and returns the base turnaround. At payment the scheduled variant substitutes the real surge extension (Section 3.5), so a quote and a later payment for identical inputs can differ when the production day falls inside a surge window.

### 3.5. Placing and Paying for Orders

Placing an order is the strict, final counterpart to the quote. An order may be placed only when its project's `state` is `APPROVED`; otherwise placement is refused with `ERR_PROJECT_NOT_APPROVED`. Placement takes the `project_id`, a `quantity`, a `finish`, a `ship_method`, a `ship_address_id`, a `payment_method`, and optionally `promo_codes`. A new order is created with `payment_status` `UNPAID` and `fulfillment_status` `NEW`, its `reorder_of_id` null, its priced fields (`unit_price_cents`, `subtotal_cents`, `discount_cents`, `shipping_cents`, `total_cents`) computed by the identical arithmetic of Section 3.4, its `paid_cents` and `refund_cents` at 0, and its `refund_destination` and `promised_ship_date` null. The `finish` must be one of the template's `allowed_finishes` (else `ERR_VALIDATION`), and the `quantity` must be positive.

Promotion eligibility is where quote and placement diverge. Under **both** the quote and placement, a promotion identified by a code in `promo_codes` is applicable only if the code exists, the running `subtotal_cents` is at least the promotion's `min_subtotal_cents` (else that promotion is rejected with `ERR_PROMO_MIN_NOT_MET`), and its `product_type_scope` is either null or equal to the ordered project's template `product_type`. If more than one promo code is supplied, every named promotion must be `stackable`; if any one is not, the whole request is rejected with `ERR_PROMO_NOT_STACKABLE`. The quote stops there and optimistically assumes each promotion is live. **Placement adds two further gates** that the quote skips: each promotion must have an open promo window at the current logical clock instant — an interval `[starts_at, ends_at]` that includes the clock — else `ERR_PROMO_NOT_ACTIVE`; and the customer's count of prior `PAID` orders that redeemed that same code must be strictly less than the promotion's `per_customer_limit`, else `ERR_PROMO_LIMIT_EXCEEDED`. These placement-only gates are evaluated in priority order: stackability first, then promo-window activeness, then the per-customer redemption limit, then the minimum-subtotal requirement. Because of this divergence, a quote can succeed while the corresponding placement is rejected for the very same inputs.

**Paying** an order advances the payment axis from `UNPAID` to `PAID`. Payment is admissible only when `payment_status` is `UNPAID` (else `ERR_ORDER_NOT_PAYABLE`) and `fulfillment_status` is `NEW`. Two further gates guard payment and are evaluated in this order: first, the scheduled production day must have room for the order's `quantity` under any governing surge cap (else `ERR_SURGE_CAPACITY_FULL`); then, if the `payment_method` is `STORE_CREDIT`, the customer's `store_credit_cents` must be at least the order's `total_cents` (else `ERR_INSUFFICIENT_STORE_CREDIT`, HTTP 402). On success the order's `payment_status` becomes `PAID` and its `paid_cents` is set equal to `total_cents`; if the method was `STORE_CREDIT`, the customer's `store_credit_cents` is debited by `total_cents`. Payment also kicks the fulfillment axis: `fulfillment_status` moves from `NEW` to `IN_PRODUCTION`, and a **production job** is spawned in `QUEUED` state with its `quantity` copied from the order and its `scheduled_date` set to the logical clock's date at payment time, along with a `surge_window_id` denormalized pointer to whichever surge window covers that date for the product type (or null if none). The order's `promised_ship_date` is fixed at this moment using the scheduled variant, and the order `version` is bumped.

The **scheduled promised ship date** uses the same calendar arithmetic as the quote, except the surge extension is real: if a surge window covers the scheduled production date for the order's product type (using the half-open coverage rule), the promised date is extended by that window's `turnaround_extra_days`; otherwise the extension is 0.

**Surge capacity** governs how much production may be scheduled on any one day. For a given scheduled date and product type, the day's capacity is the covering surge window's `capacity_per_day` when a window with matching scope covers that date (a null `product_type_scope` matches all products), and otherwise an effectively unconstrained default of 100000 units. The day's used capacity is the sum of the `quantity` of every production job scheduled on that same date whose order shares the window's product-type scope and whose `state` is `QUEUED`, `PRINTING`, or `FINISHING` — jobs that are `CANCELLED` or `DONE` do not consume capacity. The remaining capacity is the day's capacity minus that used amount, and payment is refused with `ERR_SURGE_CAPACITY_FULL` when the order's `quantity` exceeds the remaining capacity. Cancelling an order later removes its job's quantity from the used sum, restoring the day's remaining capacity.

### 3.6. Production and Shipping

A `ProductionOperator` drives the shop floor. A production job carries the `order_id` it prints, its copied `quantity`, its `scheduled_date`, its `surge_window_id`, and a `state` that begins `QUEUED`. Advancing a job steps it one stage at a time: `QUEUED` to `PRINTING`, then `PRINTING` to `FINISHING`, then `FINISHING` to `DONE`, bumping the job `version` at each step. Advancing a job that is not in an advanceable state — including one already at `DONE` — is refused with `ERR_PRODUCTION_NOT_ADVANCEABLE`; note that `DONE` marks production complete but is not a fully terminal resting state, because a later order cancellation still scraps a `DONE` job.

Only once the order's production job has reached `DONE` may a shipment be created for that order; attempting it earlier is refused with `ERR_PRODUCTION_NOT_COMPLETE`. Creating a shipment records the `order_id`, the destination `address_id` (a snapshot of the order's ship-to address at ship time), a `carrier` name, and a `method` of `STANDARD` or `EXPRESS`; the system mints a `tracking_code` and sets the shipment `state` to `LABEL_CREATED`. Shipment creation is fulfillment-neutral: the order stays `IN_PRODUCTION` — and therefore still cancellable — while the label merely exists.

Advancing a shipment steps it from `LABEL_CREATED` to `IN_TRANSIT` and then from `IN_TRANSIT` to `DELIVERED`, bumping the shipment `version` each time; advancing a shipment already at a terminal `DELIVERED` or `VOID` state is refused with `ERR_SHIPMENT_NOT_ADVANCEABLE`. The shipment's transit progress drives the order's fulfillment axis: when the shipment enters `IN_TRANSIT` the order's `fulfillment_status` becomes `SHIPPED`, and when the shipment reaches `DELIVERED` the order's `fulfillment_status` becomes `DELIVERED`. Moving a label into transit therefore requires the order still to be `IN_PRODUCTION`.

### 3.7. Cancellation, Refunds, and Reordering

A customer may **cancel** an order only while its `fulfillment_status` is `NEW` or `IN_PRODUCTION`; cancelling an order that is already `SHIPPED`, `DELIVERED`, or `CANCELLED` is refused with `ERR_ORDER_NOT_CANCELLABLE`. Cancellation supplies a `refund_destination` and is a single atomic cascade. The order's `fulfillment_status` becomes `CANCELLED`. Any production job of the order that is not already `CANCELLED` — including one that has reached `DONE` — is moved to `CANCELLED`, which both releases its scheduled-day capacity (its quantity leaves the used-capacity sum, restoring that day's remaining capacity per Section 3.5) and, in turn, voids any shipment of the order still in `LABEL_CREATED` or `IN_TRANSIT` by setting that shipment's `state` to `VOID`. Every entity touched has its `version` bumped.

If the order had been paid, cancellation also settles money: the `payment_status` moves from `PAID` to `REFUNDED`, the `refund_destination` is recorded from the request as either `WALLET` or `CARD`, and the `refund_cents` is computed accordingly. A **wallet** refund is a goodwill full refund — the entire captured `paid_cents` is credited, with no fee, and the customer's `store_credit_cents` is increased by that amount, conserving the customer's money across the pay-then-cancel round trip. A **card** refund keeps a restocking fee: the fee is the order's `subtotal_cents` multiplied by 10 percent, rounded half up to whole cents, and the `refund_cents` is the captured `paid_cents` minus that fee, floored at 0 (and no store credit is granted). For the same order, a card refund is therefore strictly smaller than a wallet refund.

**Reordering** clones a prior order's line into a new `UNPAID` order. The new order's `reorder_of_id` is set to the source order's `id`, and the source order's `quantity`, `finish`, and project are copied forward, while the customer may optionally override the `ship_address_id` and the `ship_method`. Prices are not copied — every priced field is recomputed at the current logical clock using live template prices and current pricing rules, so a reorder can cost a different amount than the original. The result is a placed-but-unpaid order that proceeds through the ordinary pay workflow.

### 3.8. Promotions and Holiday Surge Administration

A `CatalogAdmin` defines the promotional and seasonal levers. A **promotion** declares a case-sensitive, unique, non-empty `code` that customers enter, a `kind` of `PERCENT`, `FLAT`, or `FREE_SHIP`, and a `value` — a whole-percent integer for `PERCENT` (so a value of 20 means 20 percent), a cents-off amount for `FLAT`, and an ignored value treated as 0 for `FREE_SHIP`. A promotion may set a `min_subtotal_cents` gate (defaulting to 0), a `stackable` flag (defaulting to false, meaning it cannot be combined with any other promo on one order), a `per_customer_limit` (defaulting to 1, the maximum number of `PAID` orders per customer that may redeem the code), and an optional `product_type_scope` (defaulting to null; when set, the promo applies only to orders whose project template `product_type` matches).

A promotion's live intervals are declared by adding **promo windows**, each tied to its `promotion_id` with a `starts_at` and an `ends_at` describing a closed interval. A new window must not overlap any existing window of the same promotion and must additionally stand clear of every existing window by a buffer of at least 2 calendar days: the new window is accepted only when the gap from an existing window's `ends_at` to the new window's `starts_at` is at least 2 days, or the gap from the new window's `ends_at` to the existing window's `starts_at` is at least 2 days; any window that overlaps or violates that buffer is rejected with `ERR_WINDOW_OVERLAP`.

**Surge windows** model holiday demand. Each declares a `name`, a `starts_at` and `ends_at` describing a half-open interval, a `turnaround_extra_days` count of extra production days added to turnaround for jobs scheduled inside the window, a `capacity_per_day` cap on the total order quantity that may be scheduled into any single production day inside the window, and an optional `product_type_scope` (null means the surge affects all product types). A new surge window must not overlap any existing surge window; overlaps are rejected with `ERR_WINDOW_OVERLAP`, though because surge intervals are half-open, two windows that merely touch at an endpoint (one's `ends_at` equal to the next's `starts_at`) are allowed. An operator can fetch surge windows, and the production job's `surge_window_id` gives operators a convenient read-only pointer to the surge window covering a job's scheduled date.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2 and the authorization model of Section 2.1. Creating a new resource returns HTTP 201; state-changing operations on an existing resource and all reads return HTTP 200. Request and response bodies are not repeated here — reconstruct them from the workflow narratives of Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CatalogAdmin |
| POST | `/customers` | Provision a customer account | CatalogAdmin |
| GET | `/customers/{id}` | Fetch a customer | Customer, CatalogAdmin |
| POST | `/customers/{id}/credit-adjustments` | Adjust a customer's store-credit balance | CatalogAdmin |
| POST | `/customers/{id}/addresses` | Add an address-book entry | Customer |
| GET | `/customers/{id}/addresses` | List a customer's addresses | Customer, CatalogAdmin |
| POST | `/templates` | Create a product template | CatalogAdmin |
| GET | `/templates/{id}` | Fetch a template | Customer, CatalogAdmin |
| POST | `/templates/{id}/retire` | Retire a template | CatalogAdmin |
| POST | `/projects` | Create a design project | Customer |
| GET | `/projects/{id}` | Fetch a project | Customer, CatalogAdmin |
| GET | `/projects` | List/filter projects | Customer, CatalogAdmin |
| POST | `/projects/{id}/photos` | Upload a photo into a project | Customer |
| GET | `/projects/{id}/photos` | List a project's photos | Customer, CatalogAdmin |
| POST | `/projects/{id}/autolayout` | Auto-layout a project | Customer |
| POST | `/projects/{id}/proofs` | Generate a proof (OCC-guarded) | Customer |
| GET | `/projects/{id}/proofs` | List a project's proofs | Customer, CatalogAdmin |
| POST | `/proofs/{id}/approve` | Approve a proof | Customer |
| POST | `/proofs/{id}/request-changes` | Request changes on a proof | Customer |
| POST | `/projects/{id}/quote` | Provisional price and turnaround quote | Customer |
| POST | `/orders` | Place an order | Customer |
| GET | `/orders/{id}` | Fetch an order | Customer, ProductionOperator, CatalogAdmin |
| GET | `/orders` | List/filter orders | Customer, ProductionOperator, CatalogAdmin |
| POST | `/orders/{id}/pay` | Pay an order | Customer |
| POST | `/orders/{id}/cancel` | Cancel an order | Customer |
| POST | `/orders/{id}/reorder` | Reorder from a prior order | Customer |
| GET | `/orders/{id}/production-job` | List an order's production jobs | Customer, ProductionOperator, CatalogAdmin |
| POST | `/production-jobs/{id}/advance` | Advance a production job one step | ProductionOperator |
| POST | `/orders/{id}/shipments` | Create a shipment | ProductionOperator |
| GET | `/shipments/{id}` | Fetch a shipment | Customer, ProductionOperator, CatalogAdmin |
| GET | `/shipments` | List/filter shipments | Customer, ProductionOperator, CatalogAdmin |
| POST | `/shipments/{id}/advance` | Advance a shipment one step | ProductionOperator |
| POST | `/promotions` | Create a promotion | CatalogAdmin |
| GET | `/promotions/{id}` | Fetch a promotion | Customer, CatalogAdmin |
| POST | `/promotions/{id}/windows` | Add a window to a promotion | CatalogAdmin |
| GET | `/promotions/{id}/windows` | List a promotion's windows | CatalogAdmin |
| POST | `/surge-windows` | Create a surge window | CatalogAdmin |
| GET | `/surge-windows/{id}` | Fetch a surge window | CatalogAdmin, ProductionOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_VALIDATION | 422 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_TEMPLATE_NOT_FOUND | 404 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_PROOF_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_ADDRESS_NOT_FOUND | 404 |
| ERR_PROMOTION_NOT_FOUND | 404 |
| ERR_PRODUCTION_JOB_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_SURGE_WINDOW_NOT_FOUND | 404 |
| ERR_TEMPLATE_RETIRED | 409 |
| ERR_INVALID_PROJECT_STATE | 409 |
| ERR_INSUFFICIENT_PHOTOS | 422 |
| ERR_TOO_MANY_PHOTOS | 422 |
| ERR_PHOTO_LOW_RESOLUTION | 422 |
| ERR_PROOF_NOT_PENDING | 409 |
| ERR_PROJECT_NOT_APPROVED | 409 |
| ERR_PROMO_NOT_STACKABLE | 409 |
| ERR_PROMO_NOT_ACTIVE | 409 |
| ERR_PROMO_LIMIT_EXCEEDED | 409 |
| ERR_PROMO_MIN_NOT_MET | 409 |
| ERR_ORDER_NOT_PAYABLE | 409 |
| ERR_INSUFFICIENT_STORE_CREDIT | 402 |
| ERR_SURGE_CAPACITY_FULL | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_PRODUCTION_NOT_COMPLETE | 409 |
| ERR_PRODUCTION_NOT_ADVANCEABLE | 409 |
| ERR_SHIPMENT_NOT_ADVANCEABLE | 409 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_STALE_PROJECT_VERSION | 412 |
