# Styling Box API — Product Requirements Document

## 1. Introduction

This document specifies the Styling Box API, the transactional backbone of a personal styling subscription service in the spirit of a curated "fix" box. Subscribers complete a style-and-size quiz, receive periodic boxes of stylist-curated garments to try at home, keep what they like, and send the rest back — while a styling fee paid up front is credited toward whatever they keep. The platform must coordinate several parties whose concerns rarely overlap: subscribers manage their own cadence, holds, and purchases; stylists curate boxes assigned to them; and operational staff run the catalog, inventory, stylist roster, fulfillment, and time-driven housekeeping.

The engineering challenge is that a single subscriber action can ripple across many records. Checking out a box prices the kept items, credits or forfeits the styling fee, restocks or sells inventory, records fit feedback, and re-learns the subscriber's sizing — all in one transaction that must leave every derived count and balance internally consistent. This API therefore places heavy emphasis on conserved inventory invariants, deterministic money and sizing calculations, strict validation ordering, cascading state propagation between parent and child resources, and optimistic concurrency where two writers might otherwise both advance a subscription. The sections below define the global contracts first, then the business workflows in which the scattered rules are applied.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, envelope structure, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request other than public self-registration must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. When either header is missing or unrecognizable on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The single exception is subscriber self-registration, which is public and requires no headers.

The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `Client`, `Stylist`, and `OpsAdmin`.

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Anonymous`, the caller is unauthenticated and may only self-register a client; `X-User-ID`, if present, is an opaque token not tied to any persisted entity and is never compared to any resource.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`. Ownership checks on any resource that references a client compare that resource's `client_id` (or, for a `Client` itself, its own `id`) to `X-User-ID`. A subscriber owns their own client record and its fixes, holds, purchases, and returns.
- When `X-User-Role` is `Stylist`, `X-User-ID` is the `id` of the acting `Stylist`. Ownership checks on a fix compare the fix's `stylist_id` to `X-User-ID`; a stylist may only curate fixes assigned to them.
- When `X-User-Role` is `OpsAdmin`, `X-User-ID` is an opaque operational-staff identifier not tied to any persisted entity. The server may accept it for audit purposes but does not compare it to any entity's `id`; operational staff act across all resources.

When an entity-backed actor (a `Client` or `Stylist`) targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through the `limit` and `offset` query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Out-of-range or non-integer query values are coerced into range rather than rejected: a `limit` below 1 becomes 1 and above 100 becomes 100, a non-integer `limit` falls back to 10, and a negative or non-integer `offset` falls back to 0.

Unless a specific endpoint states otherwise, all list responses are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Several collection endpoints additionally accept narrowing query filters that are matched exactly against the corresponding stored field: fixes can be filtered by `status`, `stylist_id`, and `client_id`; fix items and product-scoped item listings by `status`; and feedback listings by `client_id` and `fix_item_id`.

### 2.4. Common Resource Properties and Versioning

Most resources are mutable and carry a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across all resources.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation. It supports optimistic concurrency control (see §2.6).

Two entities are append-only event records and therefore carry **only** `id` and `created_at`: a `FeedbackEntry` (an immutable fit-feedback event) and a `Hold` (an immutable vacation-hold record). Neither `updated_at` nor `version` exists on these two entities; they are never mutated after creation. All other entities — `Client`, `StyleProfile`, `Product`, `Stylist`, `Fix`, `FixItem`, `ReturnShipment`, and `Purchase` — carry the full common set.

Whenever the server recomputes a derived field on a resource (for example, a fix's counts or charge figures, or a product's inventory counts), that recomputation is a mutation of the owning resource: it refreshes `updated_at` and increments `version`.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many paths address a resource nested under one or more parents. The server validates the existence of each identifier from left to right, rejecting the request at the first identifier that does not resolve. A request for a fix under a nonexistent client fails with `ERR_CLIENT_NOT_FOUND` before the fix is ever examined; a request for a return under a nonexistent fix fails with `ERR_FIX_NOT_FOUND` first; and so on. The existence family is: `ERR_CLIENT_NOT_FOUND`, `ERR_FIX_NOT_FOUND`, `ERR_FIXITEM_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_STYLIST_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, and `ERR_PURCHASE_NOT_FOUND`, each returned with HTTP 404. A `Fix` referenced under a client that is not its owner is treated as not found under that client (`ERR_FIX_NOT_FOUND`), as is a `FixItem` not belonging to the named fix (`ERR_FIXITEM_NOT_FOUND`) or a `ReturnShipment` not belonging to the named fix (`ERR_RETURN_NOT_FOUND`).

### 2.6. Optimistic Concurrency on Fix Scheduling

Scheduling the next fix for a subscriber is the one write in the system guarded by optimistic concurrency. The request must carry `expected_client_version`, the `version` of the `Client` the caller last observed. If that value does not match the client's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This exists because a freshly scheduled fix supersedes any prior `REQUESTED` fix; if another writer has already scheduled a new fix — advancing the client's `version` and superseding the prior request — a caller working from a stale view must not create a second superseding fix. A successful schedule increments the client's `version` by one.

This is the only endpoint that consumes a version field. No other endpoint accepts or requires `expected_client_version` or any equivalent, and no other write performs a stale-version check.

### 2.7. The Inventory Conservation Invariant

Every `Product` maintains three derived counts — `available_count` (units free to reserve), `reserved_count` (units held by selected items or awaiting return receipt), and `sold_count` (units consumed) — against a base `total_stock`. At all times, for every product, the invariant `available_count + reserved_count + sold_count` equals `total_stock`, and no count is ever negative. The counts move only through these bookkeeping steps:

- **Reserve** (a stylist selects a product into a fix): `available_count` decreases by one and `reserved_count` increases by one.
- **Sell from reservation** (a selected item is kept at checkout): `reserved_count` decreases by one and `sold_count` increases by one.
- **Release** (a selected item is removed or released, or a returned item is received back): `reserved_count` decreases by one and `available_count` increases by one.
- **Direct sell** (a direct-buy purchase is placed): `available_count` decreases by the purchased `quantity` and `sold_count` increases by the same `quantity`.
- **Compensating restock** (a direct purchase is cancelled): `sold_count` decreases by the `quantity` and `available_count` increases by the same `quantity`.
- **Explicit restock** (operational staff add stock): `total_stock` increases by the added quantity and `available_count` increases by the same quantity, preserving the invariant.

An item that is returned rather than kept stays reserved (inventory unchanged) until its return is physically received, at which point the release step above runs.

### 2.8. Monetary and Sizing Precision

All money is handled in integer cents. Two figures within the charge computation are rounded half up to a whole number of cents at the point they are produced: the buy-the-look discount and the tax. Learned sizes are integers, rounded half up from their computed real value. Fit confidence is an integer between 0 and 100, rounded half up. Counts (inventory, item counts, capacity) are non-negative integers.

### 2.9. The Logical Clock and Time-Driven Operations

The system runs on a logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any explicit set it never reads real wall-clock time. Operational staff advance the clock by supplying a target instant (`to_iso8601`); the clock jumps to that instant. All time-stamped effects — a fix's `shipped_at`, `delivered_at`, `checkout_deadline`, and `scheduled_ship_date`, a return's `received_at`, and the try-at-home deadline — are computed from the logical clock at the moment of the triggering action. Cadence and try-at-home arithmetic is whole-day datetime arithmetic in UTC.

### 2.10. Validation Ordering and Precedence

When more than one thing can be wrong with a request, the server reports the failure of the highest-priority check that fails, in this fixed order:

1. **Authentication** — `X-User-ID` and `X-User-Role` present and recognizable; otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint except public self-registration.
2. **Authorization** — the role is permitted for the endpoint; otherwise `ERR_UNAUTHORIZED` (403). Applies to all endpoints.
3. **Body well-formedness** — required fields present, enum values valid, integers within range, and array-typed fields such as `kept_item_ids` actually arrays; otherwise `ERR_VALIDATION` (422). Applies to all write endpoints.
4. **Existence** — every path- or body-referenced resource exists, checked left-to-right (see §2.5); otherwise the appropriate 404 from the existence family.
5. **Ownership** — the entity-backed actor owns the target; otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to owner-scoped endpoints.
6. **Optimistic concurrency** — `expected_client_version` matches the client's current `version`; otherwise `ERR_STALE_VERSION` (412). Applies only to scheduling the next fix.
7. **State** — the target is in a valid state for the requested transition; otherwise the appropriate 409 state error (`ERR_FIX_NOT_STYLING`, `ERR_FIX_NOT_PREVIEW`, `ERR_FIX_NOT_SHIPPED`, `ERR_FIX_NOT_DELIVERED`, `ERR_FIX_TERMINAL`, `ERR_CLIENT_NOT_ACTIVE`, `ERR_CLIENT_CANCELLED`, `ERR_STYLEPROFILE_EXISTS`, `ERR_NO_PENDING_FIX`, or `ERR_RETURN_NOT_RECEIVABLE`). Applies to all state-transition endpoints.
8. **Sibling referential status** — a referenced sibling entity is in an acceptable status (a referenced product is `ACTIVE`, a referenced stylist is `ACTIVE`); otherwise `ERR_PRODUCT_UNAVAILABLE` or `ERR_STYLIST_INACTIVE` (409). Applies to selecting an item into a fix, assigning a stylist, and placing a direct purchase.
9. **Temporal windows** — checkout occurs within its deadline and hold windows do not overlap; otherwise `ERR_CHECKOUT_WINDOW_CLOSED` or `ERR_HOLD_OVERLAP` (409). Applies to checkout and hold creation.
10. **Structural constraints** — fix item-count limits, `kept_item_ids` membership, and hold date ordering; otherwise `ERR_FIX_ITEM_LIMIT`, `ERR_FIX_TOO_FEW_ITEMS`, `ERR_KEEP_ITEM_INVALID`, or `ERR_INVALID_DATE_RANGE` (422). Applies to selecting an item, submitting a preview, shipping, checkout, and hold creation.
11. **Capacity, quota, and stock** — sufficient product `available_count` and stylist not at concurrent capacity; otherwise `ERR_OUT_OF_STOCK` or `ERR_STYLIST_AT_CAPACITY` (409). Applies to selecting an item, assigning a stylist, and placing a direct purchase.

Note the two distinct 422 layers: malformed-body checks (priority 3) are evaluated before existence, ownership, and state, whereas structural business constraints (priority 10) are evaluated after state and sibling-status checks. A client that is `CANCELLED` cannot be acted upon; such attempts surface as `ERR_CLIENT_CANCELLED` at the state layer.

### 2.11. Cascading State Propagation and Reconciliation

A single action often mutates several resources. Whenever a fix is cancelled — whether directly, by supersession, or by a subscription-level cascade — each of its still-selected items is released, which restocks the owning product (see §2.7), and the assigned stylist's active-fix count is recomputed. Whenever a child's state change alters a parent's completion criteria, the parent is transitioned automatically without a separate client request: receiving the last outstanding return closes the parent fix. Each such propagation independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version` per §2.4. The subsections of §3 describe where each cascade originates.

## 3. Business Logic & Workflows

### 3.1. Subscriber Onboarding and the Style Profile

A prospective subscriber self-registers by supplying an `email` (unique across all clients), a `full_name`, a tax `region_code` (one of `CA`, `NY`, or `OR`, which later drives checkout tax), and optionally a shipment `cadence`. The `cadence` is one of `EVERY_2_WEEKS`, `MONTHLY`, `EVERY_2_MONTHS`, or `QUARTERLY`; when omitted it defaults to `MONTHLY`. A newly registered client begins in `PROSPECT` status.

A `PROSPECT` becomes a paying subscriber by completing the style-and-size quiz. The subscriber submits their declared `quiz_top_size`, `quiz_bottom_size`, and `quiz_shoe_size` (integers), a preferred `price_tier` (one of `BUDGET`, `MID`, or `PREMIUM`), and optionally a list of free-form `style_tags` (defaulting to an empty list). This creates the client's single `StyleProfile` — one profile per client, linked by `client_id` — and moves the client from `PROSPECT` to `ACTIVE`. On creation, the three learned sizes seed from the quiz: `learned_top_size` equals `quiz_top_size`, `learned_bottom_size` equals `quiz_bottom_size`, and `learned_shoe_size` equals `quiz_shoe_size`; `fit_confidence` is 0 and `feedback_count` is 0. A client that has already completed the quiz cannot complete it again; the repeat attempt is rejected with `ERR_STYLEPROFILE_EXISTS`. The profile is retrievable as a reverse lookup returning an array of zero or one profile.

### 3.2. Managing the Subscription: Cadence, Skips, Pauses, and Cancellation

Scheduling the next box is an optimistically concurrent create. The subscriber submits `expected_client_version` (see §2.6), and the client must be `ACTIVE`; a schedule against a non-active client is rejected with `ERR_CLIENT_NOT_ACTIVE`. On success, a new `Fix` is created in `REQUESTED` status with a `scheduled_ship_date` set to the current clock plus one cadence interval, where the interval is 14 days for `EVERY_2_WEEKS`, 30 days for `MONTHLY`, 60 days for `EVERY_2_MONTHS`, and 90 days for `QUARTERLY`. Any prior `REQUESTED` fix of the same client is superseded — transitioned to `CANCELLED`, releasing and restocking its selected items — and the client's `version` increments by one.

A subscriber may **skip** the upcoming box, which requires the client to be `ACTIVE` and to have exactly one `REQUESTED` fix; if there is no such single pending fix, the skip is rejected with `ERR_NO_PENDING_FIX`. Skipping pushes that fix out by one cadence: its `scheduled_ship_date` becomes its existing `scheduled_ship_date` plus one cadence interval.

Pausing an `ACTIVE` subscription moves the client to `PAUSED`. As a side effect, every fix of that client still in `REQUESTED` is cancelled; each cancelled fix releases its `SELECTED` items to `RELEASED`, restocking each owning product (its `reserved_count` decreases by one and `available_count` increases by one). Resuming a `PAUSED` subscription moves the client back to `ACTIVE` and recomputes the next `scheduled_ship_date` as the current clock plus one cadence interval. The `ACTIVE` and `PAUSED` states form a loop a subscriber may traverse repeatedly.

Cancellation permanently moves the client to `CANCELLED` and is available from either `ACTIVE` or `PAUSED`. It is blocked when the client has any fix in `SHIPPED` or `DELIVERED` — an in-flight box must complete checkout first — and such an attempt is rejected with `ERR_CLIENT_HAS_INFLIGHT_FIX`. When cancellation proceeds, every fix of the client in `REQUESTED`, `STYLING`, or `PREVIEW` is cancelled as a cascade; each cascaded fix releases its `SELECTED` items to `RELEASED` with the corresponding restock, and each affected stylist's active-fix count is recomputed. `CANCELLED` is terminal for the subscription; further actions on a cancelled client are rejected with `ERR_CLIENT_CANCELLED`.

### 3.3. Catalog, Inventory, and the Stylist Roster

Operational staff maintain the catalog. Creating a product requires a `sku` (unique across products), a `name`, a `category` (one of `TOP`, `BOTTOM`, `SHOE`, or `ACCESSORY`), a numeric `size`, a `price_cents` list price (which must be at least 0), a `total_stock` (at least 0), and optionally curation `style_tags` (defaulting to an empty list). A new product is `ACTIVE`, with `available_count` equal to `total_stock`, and `reserved_count` and `sold_count` both 0. A product may be discontinued, moving its `status` to `DISCONTINUED`; a discontinued product can no longer be selected into fixes or purchased, and referencing one where an `ACTIVE` product is required yields `ERR_PRODUCT_UNAVAILABLE`. Restocking adds units: the submitted `add_quantity` is added to both `total_stock` and `available_count`. The `ACTIVE` and `DISCONTINUED` values are the only product statuses. Reverse lookups expose the fix items that selected a product and the direct purchases of it.

The roster of stylists is likewise managed by operational staff. A stylist is created with an `email` (unique across stylists), a `name`, and optionally a `max_concurrent_fixes` capacity (defaulting to 5, and at least 1). A new stylist is `ACTIVE` with an `active_fix_count` of 0. Deactivating a stylist moves `status` to `INACTIVE`; an inactive stylist can no longer be assigned new fixes, and an assignment attempt against one is rejected with `ERR_STYLIST_INACTIVE`. The only stylist statuses are `ACTIVE` and `INACTIVE`. A stylist's `active_fix_count` is always the number of fixes assigned to that stylist whose status is `STYLING`, `PREVIEW`, `SHIPPED`, or `DELIVERED`; it is recomputed on assignment, on ship-related fix state changes, and whenever a fix is cancelled.

### 3.4. Assigning a Stylist and Curating the Box

A requested box begins its curation when operational staff assign it to a stylist, transitioning the fix from `REQUESTED` to `STYLING` and setting its `stylist_id`. Assigning a fix that is not in `REQUESTED` is rejected with `ERR_FIX_TERMINAL`. Assignment requires the owning client to be `ACTIVE` (otherwise `ERR_CLIENT_NOT_ACTIVE`), the target stylist to be `ACTIVE` (otherwise `ERR_STYLIST_INACTIVE`), and the stylist to have spare capacity — their `active_fix_count` must be strictly less than their `max_concurrent_fixes`. When the stylist is already at or above capacity, the assignment is rejected with `ERR_STYLIST_AT_CAPACITY`. On success the stylist's `active_fix_count` is recomputed (rising by one to reflect the newly styling fix). The assignment request identifies the chosen stylist by `stylist_id`.

While a fix is in `STYLING`, the assigned stylist curates it by selecting catalog products. Each selection names a `product_id` and creates a `FixItem` in `SELECTED` status, snapshotting the product's price into the item's `price_cents`, the product's size into the item's `size`, and the product's category into the item's `category`; the item is linked to its fix by `fix_id`. Selecting reserves one unit of the product (see §2.7), which requires `available_count` of at least one — an empty shelf yields `ERR_OUT_OF_STOCK` — and requires the product to be `ACTIVE`. A fix may hold at most five items; a selection that would push the count beyond that maximum is rejected with `ERR_FIX_ITEM_LIMIT`. A stylist may remove a still-`SELECTED` item, transitioning it to `RELEASED` and restocking its product (`reserved_count` down one, `available_count` up one); removal is permitted only while the fix is in `STYLING` or `PREVIEW`, and is otherwise rejected with `ERR_FIX_NOT_STYLING`; an item that is no longer `SELECTED` likewise cannot be removed and is rejected with `ERR_FIX_NOT_STYLING`. The item to remove is named by `item_id` in the path.

Once the box holds a valid number of items, the stylist submits it for preview, transitioning the fix from `STYLING` to `PREVIEW`. Submission requires the item count to be at least three and at most five; a submission with fewer than three items is rejected with `ERR_FIX_TOO_FEW_ITEMS`. The subscriber, on seeing the preview, may send it back for restyling, transitioning the fix from `PREVIEW` back to `STYLING` and reopening it for the stylist to edit — the `STYLING` and `PREVIEW` states form a revision loop that may repeat. A fix's `item_count` reflects the number of its items in `SELECTED`, `KEPT`, or `RETURNED` status. Item and preview operations that target a fix in the wrong state are rejected at the state layer: item add and submit-preview require `STYLING` (`ERR_FIX_NOT_STYLING`), and sending back a preview requires `PREVIEW` (`ERR_FIX_NOT_PREVIEW`).

### 3.5. Shipping, Delivery, and the Try-at-Home Window

When a previewed box is ready, operational staff ship it, transitioning the fix from `PREVIEW` to `SHIPPED`. Shipping requires the owning client to be `ACTIVE` and the item count to be at least three and at most five (the same bounds as preview submission, enforced with `ERR_FIX_TOO_FEW_ITEMS` when too few). Shipping records the up-front styling fee: `styling_fee_charged_cents` is set to 2000 cents (it is 0 before ship), and `shipped_at` is set to the current clock. Shipping from any state other than `PREVIEW` is rejected with `ERR_FIX_NOT_PREVIEW`.

Operational staff then mark the box delivered, transitioning the fix from `SHIPPED` to `DELIVERED`; a mark-delivered against a fix not in `SHIPPED` is rejected with `ERR_FIX_NOT_SHIPPED`. Delivery sets `delivered_at` to the current clock and computes `checkout_deadline` as `delivered_at` plus a three-day try-at-home window (the deadline instant is inclusive). Delivery also computes a **provisional** charge that assumes the subscriber keeps everything: the estimated total is written to `estimated_charge_cents`, and `shipping_fee_cents` and `tax_cents` are set for that provisional total. Before delivery, `estimated_charge_cents` is null; before checkout, `charge_cents` is null.

### 3.6. Checkout: Keeping, Returning, and Charging the Box

At checkout the subscriber decides what to keep. The request supplies `kept_item_ids`, an array of the item ids to keep, and optionally `item_feedback`, a list of fit-feedback entries (each naming a `fix_item_id` and a `rating`); each `rating` must be one of the valid rating values and each `fix_item_id` must name an item belonging to this fix, and any entry that violates either is rejected with `ERR_VALIDATION`. Checkout transitions the fix from `DELIVERED` to `CHECKED_OUT` and requires all of: the acting client owns the fix; the current clock is on or before `checkout_deadline` (the boundary instant is still allowed, and a later attempt is rejected with `ERR_CHECKOUT_WINDOW_CLOSED`); and every id in `kept_item_ids` is a `SELECTED` item of this fix (any id that is not is rejected with `ERR_KEEP_ITEM_INVALID`). A checkout against a fix not in `DELIVERED` is rejected with `ERR_FIX_NOT_DELIVERED`.

On checkout, each item named in `kept_item_ids` transitions from `SELECTED` to `KEPT`, selling its product (its `reserved_count` down one and `sold_count` up one). Every other still-`SELECTED` item transitions to `RETURNED`; a returned item's inventory stays reserved until the physical return is received. The fix's `kept_count` and `returned_count` reflect the resulting counts of `KEPT` and `RETURNED` items.

The **final** charge is then computed over the kept set. The subtotal (`subtotal_cents`) is the sum of the `price_cents` snapshots of the items in the evaluated set. The evaluated set differs by moment: the provisional computation at delivery uses **all** items of the fix (assuming keep-all), while the final computation at checkout uses **only** the items that transitioned to `KEPT`. A buy-the-look discount applies only when every item of the fix is kept and the fix holds at least one item; in that case `buy_the_look_applied` is true and the discount equals 25 percent of the subtotal, rounded half up to a whole number of cents; otherwise the discount is zero. A styling-fee credit toward the purchase equals 2000 cents whenever the evaluated set holds at least one item, and zero otherwise. The net amount is the subtotal minus the discount minus the credit, floored at zero so it is never negative.

Shipping is resolved on that net amount, and never on a total that already includes shipping. If the evaluated set holds no items, `shipping_fee_cents` is 0. Otherwise, if the net amount is at least 7500 cents, shipping is waived to 0; below that threshold, shipping is 795 cents. The taxable base is the net amount plus the shipping fee, and `tax_cents` equals that taxable base multiplied by the client's regional rate — 7.25 percent for region `CA`, 4 percent for `NY`, and 0 percent for `OR` — rounded half up in a single rounding on the aggregate base. The final total is the taxable base plus tax; it is stored as `estimated_charge_cents` for the provisional computation at delivery, and as `charge_cents` for the final computation at checkout. The provisional computation likewise sets `buy_the_look_applied`, `shipping_fee_cents`, and `tax_cents` for its keep-all assumption.

The styling fee is charged once at ship and fully accounted at checkout, so that per fix, once checked out, `styling_fee_charged_cents` equals `styling_fee_credit_cents` plus `styling_fee_forfeited_cents`. When at least one item is kept, the full charged fee becomes `styling_fee_credit_cents` (credited toward the purchase) and `styling_fee_forfeited_cents` is 0. When nothing is kept, `styling_fee_credit_cents` is 0 and the full charged fee becomes `styling_fee_forfeited_cents`.

Checkout finally resolves the fix's fulfillment path: if no items were returned (`returned_count` is zero), the fix moves immediately to `CLOSED` with no return shipment; otherwise a `ReturnShipment` is created in `LABEL_ISSUED` status, its `item_ids` listing the ids of the `RETURNED` items, and the fix remains `CHECKED_OUT` pending the return.

### 3.7. Returns and Restocking

A checked-out box with returned items carries an outstanding `ReturnShipment` linked to its fix by `fix_id`. The subscriber may mark the label handed to the carrier, transitioning the shipment from `LABEL_ISSUED` to `IN_TRANSIT`; this is owner-scoped to the subscriber who owns the parent fix. Marking a shipment that is not in `LABEL_ISSUED` is rejected with `ERR_RETURN_NOT_RECEIVABLE`. Operational staff receive the return, transitioning the shipment to `RECEIVED` from either `LABEL_ISSUED` or `IN_TRANSIT`, setting its `received_at` to the current clock, restocking every `RETURNED` item of the fix (each owning product's `reserved_count` down one and `available_count` up one), and bubbling the parent fix up to `CLOSED`. Receiving a shipment that is already `RECEIVED` is rejected with `ERR_RETURN_NOT_RECEIVABLE`. The shipment to act on is identified by `return_id` in the path; its statuses are `LABEL_ISSUED`, `IN_TRANSIT`, and `RECEIVED`. `CLOSED` and `CANCELLED` are the terminal fix states, and any transition attempt on a fix already in one of them is rejected with `ERR_FIX_TERMINAL`.

### 3.8. Fit Feedback, Sizing Learning, and Confidence

Fit feedback captured at checkout drives the platform's sizing intelligence. For each entry in the checkout's `item_feedback`, the system creates a `FeedbackEntry` for the owning client: it records the `client_id`, the `fix_item_id` of the rated item, a `product_size` snapshot of that item's size at feedback time, the item's `category`, and the subscriber's `rating`, which is one of `TOO_SMALL`, `SLIGHTLY_SMALL`, `PERFECT`, `SLIGHTLY_LARGE`, or `TOO_LARGE`. A `FeedbackEntry` is immutable once written; an individual entry is retrievable by its `feedback_id` (a `feedback_id` that resolves to no entry is rejected with `ERR_FIXITEM_NOT_FOUND`, HTTP 404), and feedback rows can be listed and filtered by `client_id` or `fix_item_id`. After the feedback rows are created, the owning client's `StyleProfile` is recomputed: its `learned_top_size`, `learned_bottom_size`, and `learned_shoe_size`, then its `fit_confidence`, and its `feedback_count` (the number of feedback rows for that client). When a checkout carries no feedback — including the automatic keep-all sweep described in §3.9 — no feedback rows are created and these figures are unchanged.

Learned sizing is computed per category over the client's feedback rows in that category. For a single feedback row, the **implied ideal** size is the row's `product_size` adjusted by its rating: add 1 for `TOO_SMALL`, add one-half for `SLIGHTLY_SMALL`, add nothing for `PERFECT`, subtract one-half for `SLIGHTLY_LARGE`, and subtract 1 for `TOO_LARGE`. The feedback rows of a category are ordered most-recent-first by `created_at` (descending), assigning ranks 0, 1, 2, and so on; ties in `created_at` are broken by the earlier `created_at` of the fix item (falling back to `created_at`, never to `id`). Each rank carries a weight equal to one-half raised to the power of the rank — so rank 0 weighs 1, rank 1 weighs one-half, rank 2 weighs one-quarter, and so on.

For the **top** and **bottom** categories, the learned size uses the decay-weighted mean over the full feedback history of that category: multiply each row's implied ideal by its rank weight, sum those products, divide by the sum of the weights, and round the result half up to an integer, stored as `learned_top_size` and `learned_bottom_size` respectively. For the **shoe** category, the learned size uses only the single most-recent shoe feedback: take the implied ideal of that latest shoe row and round it half up, stored as `learned_shoe_size` — older shoe feedback is ignored. If a category has no feedback at all, its learned size stays equal to the corresponding quiz size.

Confidence is computed over **all** of the client's feedback rows, regardless of category. Each rating contributes a match value: 1 for `PERFECT`, six-tenths for either `SLIGHTLY_SMALL` or `SLIGHTLY_LARGE`, and 0 for either `TOO_SMALL` or `TOO_LARGE`. The `fit_confidence` is 100 times the sum of the match values divided by the number of feedback rows, rounded half up to an integer between 0 and 100; when the client has no feedback, `fit_confidence` is 0.

### 3.9. The Auto-Checkout Sweep

Boxes that are never checked out must not linger past their window. An operational sweep processes every fix still in `DELIVERED` whose current clock has passed its `checkout_deadline`, auto-checking it out as keep-all: every `SELECTED` item transitions to `KEPT` (selling its product — `reserved_count` down one, `sold_count` up one) and `buy_the_look_applied` becomes true. The final charge is computed over all items (all kept), and because everything is kept the styling-fee ledger applies the full credit. Since nothing is returned, `returned_count` is zero, so the fix moves immediately to `CLOSED` with no return shipment and no feedback created.

### 3.10. Vacation Holds and Direct-Buy Purchases

A subscriber may place a vacation `Hold` over a date window, supplying a `start_date` (inclusive) and an `end_date` (exclusive) — a half-open window from start up to but not including end. The window must be non-empty, so `end_date` must be strictly after `start_date`; otherwise the request is rejected with `ERR_INVALID_DATE_RANGE`. A new hold must not overlap any existing hold for the same client; an overlapping window is rejected with `ERR_HOLD_OVERLAP`. A hold is an immutable record linked to its subscriber by `client_id`.

Outside of a fix, a subscriber may directly buy a catalog product. The purchase names a `product_id` and a `quantity` (at least 1), creating a `Purchase` in `PLACED` status linked by `client_id`, snapshotting the product's price into `unit_price_cents`, and computing `total_cents` as `unit_price_cents` multiplied by `quantity`. A direct buy requires the client not to be `CANCELLED`, the product to be `ACTIVE` (otherwise `ERR_PRODUCT_UNAVAILABLE`), and `available_count` to be at least the requested `quantity` (otherwise `ERR_OUT_OF_STOCK`); it sells the units immediately (`available_count` down by `quantity`, `sold_count` up by `quantity`). The subscriber may cancel a placed purchase they own, transitioning it from `PLACED` to `CANCELLED` and compensating the inventory (`sold_count` down by `quantity`, `available_count` up by `quantity`). `PLACED` and `CANCELLED` are the only purchase statuses, and `CANCELLED` is terminal; cancelling an already-`CANCELLED` purchase is rejected with `ERR_FIX_TERMINAL`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`; operations that modify an existing resource (including state transitions and system operations) return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Register a new subscriber (public) | Anonymous |
| GET | `/clients/{id}` | Fetch a client | Client, OpsAdmin |
| POST | `/clients/{id}/style-profile` | Complete the style-profile quiz; activates the subscription | Client |
| GET | `/clients/{id}/style-profile` | Reverse lookup: the client's style profile (array of 0..1) | Client, Stylist, OpsAdmin |
| POST | `/clients/{id}/pause` | Pause the subscription | Client |
| POST | `/clients/{id}/resume` | Resume a paused subscription | Client |
| POST | `/clients/{id}/cancel` | Cancel the subscription permanently | Client |
| POST | `/clients/{id}/skip` | Skip the next box: push the pending fix out one cadence | Client |
| POST | `/clients/{id}/fixes` | Schedule the next fix (OCC create-with-supersede) | Client |
| GET | `/clients/{id}/fixes` | Reverse lookup: fixes for a client | Client, OpsAdmin |
| GET | `/fixes/{id}` | Fetch a fix | Client, Stylist, OpsAdmin |
| GET | `/fixes` | List/filter fixes by stylist or client | Stylist, OpsAdmin |
| POST | `/fixes/{id}/assign` | Assign a stylist and start styling | OpsAdmin |
| POST | `/fixes/{id}/items` | Stylist selects a catalog product into the fix | Stylist |
| GET | `/fixes/{id}/items` | Reverse lookup: items in a fix | Client, Stylist, OpsAdmin |
| POST | `/fixes/{id}/items/{item_id}/remove` | Stylist removes a selected item (releases the reservation) | Stylist |
| POST | `/fixes/{id}/submit-preview` | Stylist submits the curated fix for client preview | Stylist |
| POST | `/fixes/{id}/request-changes` | Client sends the preview back for restyling | Client |
| POST | `/fixes/{id}/ship` | Ship the fix; charges the styling fee | OpsAdmin |
| POST | `/fixes/{id}/mark-delivered` | Mark the box delivered; opens the try-at-home window | OpsAdmin |
| POST | `/fixes/{id}/checkout` | Client checks out: keep a subset, return the rest, leave feedback | Client |
| GET | `/fixes/{id}/returns` | Reverse lookup: return shipments for a fix | Client, OpsAdmin |
| POST | `/fixes/{id}/returns/{return_id}/ship` | Client marks the return label handed to the carrier | Client |
| POST | `/fixes/{id}/returns/{return_id}/receive` | Warehouse receives the return; restocks items and closes the fix | OpsAdmin |
| POST | `/clients/{id}/holds` | Create a vacation hold window | Client |
| GET | `/clients/{id}/holds` | Reverse lookup: holds for a client | Client, OpsAdmin |
| GET | `/feedback/{feedback_id}` | Fetch a single feedback entry | Client, Stylist, OpsAdmin |
| GET | `/feedback` | List/filter feedback by client or fix item | Client, Stylist, OpsAdmin |
| POST | `/products` | Create a catalog product | OpsAdmin |
| GET | `/products/{id}` | Fetch a product | Client, Stylist, OpsAdmin |
| POST | `/products/{id}/discontinue` | Discontinue a product | OpsAdmin |
| POST | `/products/{id}/restock` | Add units to a product's stock | OpsAdmin |
| GET | `/products/{id}/fix-items` | Reverse lookup: fix items that selected this product | OpsAdmin |
| GET | `/products/{id}/purchases` | Reverse lookup: direct purchases of this product | OpsAdmin |
| POST | `/stylists` | Create a stylist | OpsAdmin |
| POST | `/stylists/{id}/deactivate` | Deactivate a stylist | OpsAdmin |
| POST | `/clients/{id}/purchases` | Direct-buy a catalog product outside a fix | Client |
| GET | `/clients/{id}/purchases` | Reverse lookup: purchases by a client | Client, OpsAdmin |
| POST | `/purchases/{id}/cancel` | Cancel a direct purchase (compensating restock) | Client |
| POST | `/_clock/set_current_utc` | Set the logical clock | OpsAdmin |
| POST | `/_ops/run-checkout-sweep` | Auto-checkout every delivered fix past its deadline | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_FIX_NOT_FOUND` | 404 |
| `ERR_FIXITEM_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_STYLIST_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_PURCHASE_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STYLEPROFILE_EXISTS` | 409 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_CLIENT_CANCELLED` | 409 |
| `ERR_CLIENT_HAS_INFLIGHT_FIX` | 409 |
| `ERR_NO_PENDING_FIX` | 409 |
| `ERR_FIX_NOT_STYLING` | 409 |
| `ERR_FIX_NOT_PREVIEW` | 409 |
| `ERR_FIX_NOT_SHIPPED` | 409 |
| `ERR_FIX_NOT_DELIVERED` | 409 |
| `ERR_FIX_TERMINAL` | 409 |
| `ERR_RETURN_NOT_RECEIVABLE` | 409 |
| `ERR_PRODUCT_UNAVAILABLE` | 409 |
| `ERR_STYLIST_INACTIVE` | 409 |
| `ERR_CHECKOUT_WINDOW_CLOSED` | 409 |
| `ERR_HOLD_OVERLAP` | 409 |
| `ERR_FIX_ITEM_LIMIT` | 422 |
| `ERR_FIX_TOO_FEW_ITEMS` | 422 |
| `ERR_KEEP_ITEM_INVALID` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_OUT_OF_STOCK` | 409 |
| `ERR_STYLIST_AT_CAPACITY` | 409 |
