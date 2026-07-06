# Office-Pantry Subscription API — Product Requirements Document

## 1. Introduction

This document specifies the Office-Pantry Subscription API, the operational backbone of a SnackNation-style curated pantry service. The system stitches together three business concerns that are usually kept apart: a **subscription and billing** layer that meters office headcount against tiered plans, an **inventory and rotation** layer that projects par-level restocks against dietary preferences, and a **fulfillment and dispute** ledger that reconciles what was promised at dispatch against what was actually delivered on-site. These concerns interact — a paused subscription must not merely stop billing; it must invalidate the in-flight rotation, cancel scheduled and in-transit deliveries, and refund the client for anything the courier already put in a truck. Similarly, a dispute filed by a location manager forty-eight hours after delivery must recompute charges from reported actuals and credit the client's running balance, which the next rotation close will then draw down against the invoice.

The API serves three peer roles with very different views of the world: a **platform operations** role that runs the fleet, generates rotations, and closes billing cycles; a **client-side administrator** role that opens the subscription, expresses dietary constraints, pauses or cancels service, and pays invoices; and a **location manager** role that reports what actually landed on the shelf. Because every state change on one role's surface ripples into another's ledger, the specification below emphasizes cascade semantics, snapshot semantics, and rounding order — the places where a naive implementation and a correct one diverge.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID` identifies the acting principal, and `X-User-Role` declares the principal's operational capacity. A request missing either header is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401), and a request whose `X-User-Role` is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes three peer roles:

- `PlatformAdmin` — operations staff running the SnackNation platform. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it in audit logs but does not compare it against any entity's `id`. Platform admins configure the catalog (creating a `Plan` or a `Product`), onboard clients, activate subscriptions, generate rotations, dispatch and finalize deliveries, close rotations, resolve invoice disputes, and run the overdue-invoice sweep.
- `ClientAdmin` — administrator for a specific office `Client`. When `X-User-Role` is `ClientAdmin`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` (a `Subscription`, `Location`, `Preference`, `Invoice`, `Feedback`) compare that resource's `client_id` foreign-key field to `X-User-ID`. A client admin manages the subscription lifecycle, declares locations and preferences, submits feedback, and pays invoices for their own client only.
- `LocationManager` — on-site manager for a specific `Location`. When `X-User-Role` is `LocationManager`, `X-User-ID` is the `id` of the acting `Location`; ownership checks on any resource that references a `Location` (a `ParLevel`, `Delivery`, `DeliveryLine`) compare the resource's `location_id` foreign-key field to `X-User-ID`. Location managers set par levels, confirm deliveries, file disputes, and report actual units received.

An operation that requires role-scoped ownership but is invoked by an entity-backed principal whose `X-User-ID` does not match the target resource's owning-entity id is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter names how many items to skip and defaults to 0. Unless a subsection below overrides it, every list endpoint returns resources sorted by `created_at` in ascending order.

Every list response includes four pagination fields inside `meta`: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

The majority of persistent resources — `Client`, `Plan`, `Subscription`, `Location`, `Product`, `ParLevel`, `RotationCycle`, `Delivery`, `DeliveryLine`, `Invoice` — share a system-managed property block:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource's fields, including mutations driven by state transitions and cascades.
- `version` (integer): a monotonically increasing counter that begins at 1 on creation and increments by one on every mutation. This is the concurrency token described in §2.8.

Two entities carry a lightweight envelope only: `Preference` and `Feedback` are append-only records and expose only `id` and `created_at` — they have no `updated_at` and no `version`.

Every mutation described anywhere in this document — a state transition, a computed-field refresh, a cascade side effect — refreshes `updated_at` and increments `version` on the affected resource. This applies uniformly and is not restated at every side-effect line.

### 2.5. Nested Resource Retrieval

Endpoint paths carry resource identifiers left-to-right (for example, a listing of preferences under a client, or par-levels under a location). The server validates each identifier in the order it appears in the path. The first identifier that does not resolve produces the most-specific "not found" error for that resource type — `ERR_CLIENT_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_ROTATION_CYCLE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_DELIVERY_LINE_NOT_FOUND` — and the request short-circuits (all HTTP 404). References to a `Product` id or a `Plan` id inside a request body follow the same discipline and yield `ERR_PRODUCT_NOT_FOUND` or `ERR_PLAN_NOT_FOUND` respectively. A retrieval of a `Feedback` id that does not resolve yields `ERR_FEEDBACK_NOT_FOUND` (HTTP 404); an unresolved par-level id at `/par-levels/{id}` surfaces as `ERR_LOCATION_NOT_FOUND` (HTTP 404), since no distinct par-level not-found code is defined in this API. Left-to-right lookup precedes every business check, so a client not-found error always wins over a state or capacity error further down the path.

### 2.6. Monetary Precision and Rounding

All monetary values in the system are integer cents. Two calculation regimes stack on top of that integer discipline:

- **Per-line rounding first.** Whenever a per-line rounded quantity is combined into a total (for example, a per-line service fee at a `MICRO_MARKET` or a per-line bulk discount), each line is rounded to integer cents independently using round-half-up, then the rounded per-line quantities are summed. The system never rounds a total that was itself summed from unrounded fractional intermediates.
- **Discount-then-round-then-add for subscription fees.** The tiered subscription fee (§3.7) applies its volume discount to the raw per-employee amount, rounds that discounted quantity to integer cents using round-half-up, and only then adds the base fee. Alternative orderings (summing then rounding) are rejected by the specification.

The satisfaction score is the sole non-cent monetary-adjacent value: it is expressed to two decimal places using round-half-up (§3.8).

### 2.7. Hierarchical Consistency and Cascade Semantics

The pause and cancel operations on an `ACTIVE` subscription drive the deepest cascade in the system — a chain that mutates entities across four layers, where every hop is caused by the previous hop's mutation rather than by the origin action. This section states the invariant; §3.3 walks the hops in narrative form.

- **Hop 1** — the origin transition on the `Subscription` moves `status` from `ACTIVE` to `PAUSED` (or to `CANCELLED`).
- **Hop 2** — that mutation causes the currently-`OPEN` `RotationCycle` under the subscription to transition from `OPEN` to `INVALIDATED`. This is not a separate client action; it is a system transition caused by hop 1.
- **Hop 3** — the `INVALIDATED` mutation on the rotation cycle causes every `Delivery` under that cycle whose `status` is `SCHEDULED` or `EN_ROUTE` to transition to `CANCELLED`. Terminal deliveries (`DELIVERED`, `DISPUTED`, `FINALIZED`, previously `CANCELLED`) are not touched.
- **Hop 4** — for each `EN_ROUTE` delivery cancelled in hop 3 (and only for `EN_ROUTE`; `SCHEDULED` deliveries cost the client nothing), the cancellation computes `dispute_credit_cents` equal to that delivery's `provisional_cents` and credits it to the client's `credit_balance_cents`. A `SCHEDULED` delivery had no provisional cost committed against the client and therefore receives no credit.

In parallel, when a rotation cycle transitions to `INVALIDATED`, every `Invoice` bound to the affected `Client` whose `dispute_status` is `CLEAN` and whose `payment_status` is `UNPAID` flips its `dispute_status` to `UNDER_DISPUTE` — the fan-out is scoped by `client_id` rather than restricted to invoices from the just-invalidated cycle's subscription, since a client's other historical invoices are billed against the same running ledger the origin action perturbs. This is a distinct fan-out on the invoice's dispute dimension and is independent of the four-hop delivery/credit chain.

Cascade transitions are ordinary mutations for the purposes of §2.4: every affected entity has its `version` incremented and its `updated_at` refreshed exactly as if the transition had been a direct client action.

The `Delivery` resolve-dispute path is a shallower, second-depth cascade: computing `dispute_credit_cents` at resolve time itself causes the client's `credit_balance_cents` to be incremented. The credit hop would not happen without the just-computed dispute credit; it is not a side effect of the operator's action but of the dispute-credit mutation itself.

### 2.8. Optimistic Concurrency Control

Creating a subscription against a stale view of a client is the sole endpoint in this API guarded by optimistic concurrency control. A subscription-create request must carry `expected_client_version` as a non-optional field whose value is the `version` of the target `Client` at the moment the client admin read it. If `expected_client_version` does not equal the client's current `version`, the request is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412) — this expresses that another writer has advanced the client's version (for example, a `PATCH` to headcount that would change billing tier and therefore what the subscription's snapshot must encode) since the current writer last observed the client, and the current writer's view is therefore stale. The reject is framed strictly as a stale-version condition on the parent `Client`: it does not depend on requests overlapping in time.

No other endpoint in this API accepts a version field. Endpoints that do not appear in the OCC rule above do not perform version-based rejection.

### 2.9. Dietary Preferences and Product Placement Safety

Every `Client` carries a list of `Preference` blocks, each of which names a single `dietary_flag` that the client wishes to exclude. A `Product` carries an array `dietary_flags` describing its own attributes (for example, `NUT_FREE`, `VEGAN`, `GLUTEN_FREE`). The invariant is that a product carrying any dietary flag that appears in any of the client's preferences must not be placed at any of that client's locations. Attempts to violate the invariant on either the par-level surface (setting a `ParLevel` for a blocked product) or the feedback surface (submitting a `swap_suggestion_product_id` for a product the client blocks) are rejected with `ERR_DIETARY_PREFERENCE_VIOLATION` (HTTP 422).

A parallel placement constraint tracks physical suitability: a `Product` with `requires_refrigeration` set to true may be placed only in `Location`s whose `kind` is `FRIDGE` or `MICRO_MARKET`. Attempts to set a `ParLevel` for a refrigerated product at a `PANTRY` are rejected with `ERR_REFRIGERATION_MISMATCH` (HTTP 422).

### 2.10. Location Capacity and Delivery Scheduling

Each `Location` declares its `capacity_units`, and the sum of `par_units` over all `ParLevel` rows attached to that location must never exceed the declared capacity. A par-level creation that would push the running sum above `capacity_units` is rejected with `ERR_LOCATION_CAPACITY_EXCEEDED` (HTTP 422).

Deliveries at the same location must be spaced with a 24-hour buffer: a proposed `scheduled_at` must be at least 24 hours later than any existing non-cancelled delivery's `scheduled_at` at that same location. An exact 24-hour gap is permitted; anything strictly less than 24 hours is rejected with `ERR_DELIVERY_SCHEDULE_CONFLICT` (HTTP 409).

Deliveries generated within a rotation cycle must also live inside that cycle's window. The window is expressed as a half-open interval `[effective_from, effective_to)` — inclusive at the start, exclusive at the end. A delivery whose `scheduled_at` falls outside its cycle's `[effective_from, effective_to)` is rejected with `ERR_ROTATION_CYCLE_OVERLAP` (HTTP 422). The same error covers rotation-cycle creation itself: when the system opens a new cycle on subscription activation or resume, the new `[effective_from, effective_to)` must not overlap any existing `OPEN` cycle for the same subscription, where overlap is defined as two half-open intervals `[a, b)` and `[c, d)` such that `a` is strictly less than `d` and `c` is strictly less than `b`. Terminal cycles (`CLOSED` and `INVALIDATED`) represent historically-terminated windows and do not gate new-cycle creation — consistent with §3.3's rule that "the invalidated cycle is not resurrected; the new cycle is a fresh window."

### 2.11. Cross-Cutting Business Constraints and Validation Priority

The system runs its validations in a fixed priority order so that the returned error is deterministic when a request would fail multiple checks. The evaluation walks the following classes in the order shown; the first class that fires produces the response, and no later class is evaluated:

1. **Authentication headers present.** Missing `X-User-Role` or `X-User-ID` — `ERR_MISSING_AUTH_HEADERS` (401). Applies to every endpoint except unauthenticated catalog reads (there are none in this API's regular surface, so in practice this rule fires on every request).
2. **Role permitted.** The declared role is not permitted for this endpoint per the RBAC surface — `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. **Path parent exists — Client.** Any endpoint whose path contains `/clients/{id}` — `ERR_CLIENT_NOT_FOUND` (404).
4. **Path parent or foreign key exists — Location.** Any endpoint whose path contains a location id or whose body references `location_id` — `ERR_LOCATION_NOT_FOUND` (404).
5. **Path parent exists — Subscription.** Any endpoint whose path contains a subscription id — `ERR_SUBSCRIPTION_NOT_FOUND` (404).
6. **Path parent exists — Delivery.** Any endpoint whose path contains a delivery id — `ERR_DELIVERY_NOT_FOUND` (404).
7. **Path parent exists — RotationCycle.** Any endpoint whose path contains a rotation-cycle id — `ERR_ROTATION_CYCLE_NOT_FOUND` (404).
8. **Path parent exists — Invoice.** Any endpoint whose path contains an invoice id — `ERR_INVOICE_NOT_FOUND` (404).
9. **Foreign-key resource exists — Product.** Any endpoint that references a `product_id` in body or path — `ERR_PRODUCT_NOT_FOUND` (404).
10. **Foreign-key resource exists — Plan.** Any endpoint that references a `plan_id` — `ERR_PLAN_NOT_FOUND` (404).
11. **Ownership.** For entity-backed roles (`ClientAdmin`, `LocationManager`) targeting a scoped resource, `X-User-ID` does not match the owning-entity id — `ERR_FORBIDDEN_OWNERSHIP` (403).
12. **State admits the transition.** The target entity is not in a state from which the requested transition is valid, or a rotation cycle referenced by a delivery-generator call is not `OPEN` — `ERR_INVALID_STATE` (409).
13. **Cross-entity active subscription.** Dispatch and confirm require the parent subscription's `status` to be `ACTIVE` — `ERR_SUBSCRIPTION_NOT_ACTIVE` (409).
14. **Invoice dispute state permits payment.** Paying an invoice requires the invoice's `dispute_status` to be `CLEAN` or `RESOLVED` — `ERR_INVOICE_UNDER_DISPUTE` (409).
15. **Dietary preference.** A par-level or a feedback swap-suggestion whose product's `dietary_flags` overlap the client's `Preference` list — `ERR_DIETARY_PREFERENCE_VIOLATION` (422).
16. **Refrigeration placement.** A par-level of a `requires_refrigeration` product at a `PANTRY` location — `ERR_REFRIGERATION_MISMATCH` (422).
17. **Capacity.** Sum of `par_units` at the target location would exceed `capacity_units` — `ERR_LOCATION_CAPACITY_EXCEEDED` (422).
18. **Delivery schedule buffer.** Proposed `scheduled_at` strictly less than 24 hours after an existing non-cancelled delivery at the same location — `ERR_DELIVERY_SCHEDULE_CONFLICT` (409).
19. **Rotation window and interval adjacency.** A new cycle overlaps an existing cycle, or a delivery is generated outside its cycle's `[effective_from, effective_to)` window — `ERR_ROTATION_CYCLE_OVERLAP` (422).
20. **At most one non-terminal subscription per client.** A client attempting to create a subscription while it already has one whose `status` is not `CANCELLED` — `ERR_SUBSCRIPTION_ALREADY_ACTIVE` (409).
21. **Non-empty assortment.** The delivery generator's candidate product set is empty after applying dietary and refrigeration filters — `ERR_EMPTY_ASSORTMENT` (422).
22. **Headcount floor.** `headcount` would fall below 1 on subscription-create or on a headcount patch — `ERR_INVALID_HEADCOUNT` (422).
23. **Client-version OCC.** `expected_client_version` does not equal the target client's current `version` — `ERR_STALE_CLIENT_VERSION` (412).

Because the ordering is strict, a mid-flight authorization failure always surfaces above a state error, a state error above a business-safety check, and a business-safety check above the OCC verdict. A single request that would fail on both a stale-version condition and, say, a headcount floor will surface the headcount error first — the stale-version verdict is reserved for requests that pass every earlier check and only lose the version race. Malformed or missing required fields in a request body produce `ERR_INVALID_REQUEST` (HTTP 400) at the intake boundary before any of the priority-ordered checks run.

## 3. Business Logic & Workflows

### 3.1. Catalog and Client Onboarding

Onboarding starts with the platform team populating two catalogs. A platform admin registers each **Plan** by supplying a `tier` label (for example, `STARTER`, `GROWTH`, `ENTERPRISE`), a `billing_type` that is either `PER_EMPLOYEE` or `FLAT`, and the numeric fields the billing engine will need at close time: `base_fee_cents`, `per_employee_fee_cents`, `flat_fee_cents`, `volume_discount_threshold_headcount`, and `volume_discount_pct`. All four monetary fields are cent-denominated integers no less than zero, and `volume_discount_pct` is a fraction between 0.0 and 1.0 inclusive (a value of 0.10 expresses a ten-percent discount). A `PER_EMPLOYEE` plan ignores its `flat_fee_cents` at billing time; a `FLAT` plan ignores its `base_fee_cents`, `per_employee_fee_cents`, `volume_discount_threshold_headcount`, and `volume_discount_pct`. `volume_discount_threshold_headcount` is a required field on every plan-create body (including `FLAT` plans, where it is stored but never consulted) and must be at least 1. The plan tier is unique across active plans, and a create attempt that duplicates a `tier` is rejected at the intake boundary as `ERR_INVALID_REQUEST` (HTTP 400).

Products are registered similarly. Each **Product** carries a unique `sku`, a display `name`, a `category` drawn from `SNACK`, `BEVERAGE`, `MEAL`, or `CANDY`, an array of `dietary_flags`, a `unit_cost_cents` cost per unit no less than zero, and a `requires_refrigeration` boolean that defaults to false. The `sku` is unique across active products, and a create attempt that duplicates an existing `sku` is rejected at the intake boundary as `ERR_INVALID_REQUEST` (HTTP 400). Whenever a product's unit cost changes, existing par levels and delivery lines are unaffected — line billing always uses the price snapshot captured at line creation, as detailed in §3.5.

Once catalogs are in place, a platform admin registers each **Client** office with a `name` and an initial `headcount`. `headcount` must be at least 1; any create or later patch that would drop it below 1 is rejected with `ERR_INVALID_HEADCOUNT`. A newly created client has `credit_balance_cents` set to 0 and `active_subscription_id` set to null. When operations staff subsequently adjust the office's employee count, they submit the new `headcount` value; the client's `version` increments, which becomes the concurrency token the client admin must observe before creating any subscription (§2.8, §3.3).

Client-side onboarding continues under a client admin. The admin declares **Locations** at the office — each `Location` has a `name`, a `kind` drawn from `PANTRY`, `FRIDGE`, or `MICRO_MARKET`, an integer `capacity_units` no less than 1, and an optional `service_fee_bps` service-fee percentage expressed in basis points between 0 and 10000 inclusive (when omitted from the create body, `service_fee_bps` defaults to 0). Service fees typically run higher on micro-markets than on pantries because a checkout kiosk has an operating cost the standard station does not, but the numeric value is a per-location input rather than a hardcoded rate. The client admin also declares **Preference** blocks by naming a single `dietary_flag` per block; the pair of `client_id` and `dietary_flag` is unique, and a duplicate is rejected at the intake boundary as `ERR_INVALID_REQUEST` (HTTP 400). There is no bulk preference upload — each blocked attribute is its own row, and each is subject to the priority checks of §2.11.

### 3.2. Assortment: Products at Locations

With locations declared and products registered, the location's on-site manager attaches **Par Levels** to their location. Each `ParLevel` binds a `product_id` to the location with a target restock quantity, `par_units`, that is at least zero. The pair `(location_id, product_id)` is unique per location, and a duplicate create is rejected at the intake boundary as `ERR_INVALID_REQUEST` (HTTP 400). Three checks fire in the priority order of §2.11 before a par-level is accepted: the product's `dietary_flags` must not overlap the client's preference blocks (`ERR_DIETARY_PREFERENCE_VIOLATION`), the product's `requires_refrigeration` flag must be compatible with the location's `kind` (`ERR_REFRIGERATION_MISMATCH`), and the sum of `par_units` over the location's existing par-levels plus the new row must not exceed `capacity_units` (`ERR_LOCATION_CAPACITY_EXCEEDED`).

A client subsequently changing its preference list does not retroactively remove existing par-levels; those rows stand until the location manager takes them down. However, the delivery generator's per-cycle assortment filter (§3.4) re-evaluates preferences at generation time, so a preference added after a par-level exists will still surface in the assortment filter, blocking that par-level's product from the next rotation.

### 3.3. The Subscription Lifecycle

A client admin opens a subscription by naming a `plan_id` and supplying `expected_client_version` — the `Client.version` value the admin observed when preparing the request. The server rejects the create with `ERR_STALE_CLIENT_VERSION` if the client's current `version` has moved on since. On success, a new `Subscription` is created with `status` `DRAFT`, `client_id` bound to the target client, `plan_id` bound to the named plan, and `plan_version_snapshot` set to the `Plan`'s current `version` at that instant — subsequent plan edits do not disturb this subscription's billing. The server also sets the client's `active_subscription_id` to the new subscription's id and increments `client.version`. The per-client invariant — at most one non-terminal subscription — is enforced at this boundary: if the client already has a subscription in `DRAFT`, `ACTIVE`, or `PAUSED`, the create is rejected with `ERR_SUBSCRIPTION_ALREADY_ACTIVE`. Note that a `CANCELLED` subscription is terminal and does not count against this limit.

**Activating the subscription.** Activation is a platform-admin operation on a `DRAFT` subscription. Three preconditions must hold in addition to the state check: the subscription must be `DRAFT`, the client must have declared at least one `Location`, and at least one `ParLevel` must exist across the client's locations. A violation of any of these three preconditions is surfaced as `ERR_INVALID_STATE` (HTTP 409). Activation flips `status` from `DRAFT` to `ACTIVE`, stamps `updated_at`, and opens the very first rotation cycle. That first `RotationCycle` is created with `cycle_index` equal to 1, `effective_from` set to the current server clock, `effective_to` set to `effective_from` plus 30 days, and `status` `OPEN`. Cycle windows are contiguous — the `effective_to` of one cycle is identical to the `effective_from` of the next cycle on the same subscription — and a new cycle's half-open interval must not overlap any prior cycle's half-open interval (§2.10).

**Pausing.** The client admin can pause an `ACTIVE` subscription. Beyond the state and ownership checks, pause has no additional inputs. Pause flips `status` to `PAUSED`, server-stamps `paused_at` to the current clock, and increments `cumulative_active_days` by the whole number of days between the subscription's most recent `ACTIVE` entry and the current clock — a fractional partial day is dropped (the increment is computed by taking the elapsed time and flooring it to whole days). Pause is also the origin of the four-hop cascade of §2.7: the currently-`OPEN` rotation cycle transitions from `OPEN` to `INVALIDATED`; that cycle-mutation causes every under-cycle delivery whose `status` is `SCHEDULED` or `EN_ROUTE` to move to `CANCELLED`; and for each `EN_ROUTE` delivery so cancelled, the delivery's `dispute_credit_cents` is set to that delivery's `provisional_cents` and the client's `credit_balance_cents` is credited by that amount. In parallel, every `Invoice` bound to the same `Client` whose `dispute_status` is `CLEAN` and whose `payment_status` is `UNPAID` transitions its dispute dimension from `CLEAN` to `UNDER_DISPUTE` (the fan-out is scoped by `client_id`, per §2.7).

The compensating-action invariant that ties these hops together is this: for every delivery that was in flight (`EN_ROUTE`) at pause, the amount credited to the client equals the provisional charge that would have been billed if the delivery had gone through. A `SCHEDULED` delivery has never been dispatched, has no `provisional_cents`, and therefore requires no credit — cancelling it is free of ledger side effects.

**Resuming.** The client admin can resume a `PAUSED` subscription. Resume flips `status` back to `ACTIVE`, clears `paused_at` to null, and opens a new `RotationCycle` with `cycle_index` equal to the previous cycle's index plus one, `effective_from` set to the current clock, and `effective_to` set to `effective_from` plus 30 days. The invalidated cycle is not resurrected; the new cycle is a fresh window.

**Cancelling.** The client admin can cancel a subscription from either `ACTIVE` or `PAUSED`. Cancellation from `ACTIVE` triggers the same fan-out as pause on the currently-`OPEN` rotation cycle; cancellation from `PAUSED` has no in-flight cycle and therefore no delivery cascade — the client's OPEN cycle was already invalidated at pause time. Both cancellation paths flip `status` to `CANCELLED`, server-stamp `cancelled_at` to the current clock, and clear the client's `active_subscription_id` back to null. `CANCELLED` is the sole terminal state for a subscription; there is no reopen.

The active subscription's `cumulative_active_days` tracks the total whole logical days the subscription has spent in `ACTIVE` across all pause/resume loops. It is incremented only on transitions out of `ACTIVE` (that is, at pause and at cancel-from-active), never mid-`ACTIVE`.

### 3.4. Rotation Cycles and Delivery Generation

A rotation cycle is the billing and delivery unit. Each `RotationCycle` binds to its parent subscription via `subscription_id`. Its `status` is `OPEN` while accepting deliveries, transitions to `CLOSED` when the platform admin closes it after the window has elapsed (§3.7), and transitions to `INVALIDATED` when the parent subscription is paused or cancelled from `ACTIVE`. `CLOSED` and `INVALIDATED` are both terminal.

Within an `OPEN` cycle, a platform admin generates a **Delivery** by supplying a `location_id` — the target location, which must belong to the subscription's client (a delivery-generator call whose `location_id` resolves to a location under a different client is rejected as `ERR_INVALID_STATE` (HTTP 409)) — and a `scheduled_at` timestamp. The delivery is rejected if the cycle is not `OPEN` (`ERR_INVALID_STATE`), if `scheduled_at` falls outside the cycle's `[effective_from, effective_to)` window (`ERR_ROTATION_CYCLE_OVERLAP`), or if `scheduled_at` is strictly less than 24 hours after any existing non-cancelled delivery at the same location (`ERR_DELIVERY_SCHEDULE_CONFLICT`). An exact 24-hour spacing is permitted.

If those checks pass, the delivery generator projects the location's assortment through **par-projection**. It gathers every `ParLevel` at the target location and, in a first pass, sets each projected line's planned quantity equal to that par-level's `par_units`. It then filters the candidate set by removing any product whose `dietary_flags` intersect the client's preference blocks, and additionally removes any candidate whose `requires_refrigeration` is true when the target `Location.kind` is `PANTRY`. Products at `FRIDGE` or `MICRO_MARKET` locations are unaffected by the refrigeration filter. The surviving candidates are ranked by `ParLevel.par_units` in descending order, with ties broken by `ParLevel.created_at` in ascending order. If the surviving set is empty after filtering, the request is rejected with `ERR_EMPTY_ASSORTMENT`.

For each surviving candidate the generator writes a `DeliveryLine`. Each line captures `planned_units` from the par-level, snapshots the current `Product.unit_cost_cents` into `unit_price_cents_snapshot`, and snapshots the current `Location.service_fee_bps` into `service_fee_bps_snapshot`. Subsequent price and fee edits on the parent `Product` or `Location` do not disturb existing lines — the billing engine reads exclusively from the snapshots. The `actual_units` field is initially null and defaults to `planned_units` at any later charge computation that runs before actuals are reported. The par-projection is a forward estimate: `actual_units` reported at confirm time may be strictly less than `planned_units` but must never exceed it (the constraint on `actual_units` is that it is at least zero and at most `planned_units`).

Every delivery-generator call increments the parent rotation cycle's `version`. The cycle otherwise remains `OPEN` until the platform admin closes it.

### 3.5. Delivery Fulfillment: Dispatch, Confirm, Actuals

Deliveries carry a six-state lifecycle: `SCHEDULED` on creation, `EN_ROUTE` at dispatch, `DELIVERED` at confirm, optionally `DISPUTED` if the location manager files a dispute, `FINALIZED` at resolve or auto-finalize, and `CANCELLED` if the pause/cancel cascade catches the delivery in-flight.

**Dispatch.** A platform admin dispatches a `SCHEDULED` delivery. Dispatch requires the delivery to be `SCHEDULED`, the parent subscription's `status` to be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`), the parent rotation cycle's `status` to be `OPEN`, and the current clock to be less than 24 hours past `scheduled_at` — that is, the dispatch window closes exactly 24 hours after the scheduled time. Dispatch flips `status` to `EN_ROUTE`, server-stamps `dispatched_at` to the current clock, and computes `provisional_cents` under the forward-looking regime detailed below.

**Confirm.** The location manager confirms the delivery has arrived. Confirm requires the delivery to be `EN_ROUTE`, the manager's `X-User-ID` to match the delivery's `location_id`, and the parent subscription's `status` to still be `ACTIVE`. Confirm flips `status` to `DELIVERED` and server-stamps `delivered_at`.

**Reporting actuals.** Between confirm and either dispute or auto-finalize, the location manager may report `actual_units` per line by patching individual delivery-lines. Each report is bounded — `actual_units` is at least zero and at most the line's `planned_units` — and the line's `version` increments on each patch.

**Provisional and final charge formula.** The charge formula fires twice — once forward-looking at dispatch (writing `provisional_cents`), and once chronologically at finalize or resolve-dispute (writing `final_cents`). Both variants share the same shape and constants; they differ only in which quantity per line drives the arithmetic.

The provisional variant, evaluated at dispatch, walks each `DeliveryLine` for the delivery and computes three per-line quantities from three inputs plus the parent location's `kind`:

- The raw per-line amount is the line's `planned_units` multiplied by its `unit_price_cents_snapshot`.
- The per-line fee amount is zero when the location's `kind` is `PANTRY` or `FRIDGE`. When the location's `kind` is `MICRO_MARKET`, the per-line fee is the raw amount multiplied by the line's `service_fee_bps_snapshot` divided by 10000, then rounded to integer cents using round-half-up. This isolation of the service fee to micro-markets is deliberate: pantries and refrigerators have no operator-attended checkout to fund.
- The per-line bulk discount is zero when the line's `planned_units` is strictly less than 100. When `planned_units` is at least 100 (the boundary is inclusive), the per-line discount is the raw amount multiplied by 0.05, rounded to integer cents using round-half-up. This is a five-percent discount on bulky line items.
- The per-line total is the raw amount plus the per-line fee minus the per-line discount.

`provisional_cents` is the sum of the per-line totals over the delivery's lines. The interaction of the `MICRO_MARKET` branch with the 100-unit bulk boundary produces four regimes per line — fee off or on, discount off or on — and the branches are independent, so a single line at a micro-market with a 100-unit shipment carries both a rounded per-line fee and a rounded per-line discount, each computed from the raw amount and each rounded independently before subtraction.

The final variant, evaluated at finalize or resolve-dispute, is identical in shape but reads `actual_units` in place of `planned_units`. The raw amount, the fee comparison, and the discount comparison are all recomputed against `actual_units`; the bulk boundary is still `actual_units` at least 100. When actuals equal planned (the auto-finalize path with no dispute), `final_cents` equals `provisional_cents`. When actuals are strictly less than planned (the resolve-dispute path), `final_cents` may be lower — and, critically, may cross the 100-unit boundary in the opposite direction, so a line that earned the 5% discount at dispatch may not earn it at finalize, and vice versa.

### 3.6. Disputes, Actuals, and Client Credit

Between confirm and 48 hours after confirm, the location manager may file a **dispute** by supplying `dispute_reason` — a free-text explanation of what went wrong on the shelf. Dispute requires the delivery to be `DELIVERED`, the manager's `X-User-ID` to match the delivery's `location_id`, and the current clock to be strictly less than 48 hours past `delivered_at`. Dispute flips `status` to `DISPUTED` and records `dispute_reason` from the request payload; it does not by itself compute any charge.

While a delivery is `DISPUTED`, the location manager continues to report `actual_units` per line as needed. Once every `DeliveryLine` under the delivery has an `actual_units` value set (not null), the platform admin can **resolve the dispute**. Resolve requires the delivery to be `DISPUTED` and requires actuals-set on every line; it then computes `final_cents` under the chronological variant and computes `dispute_credit_cents` as the sum over all lines where `actual_units` is strictly less than `planned_units` of the quantity `(planned_units - actual_units)` multiplied by `unit_price_cents_snapshot`. In other words, the credit is the unit shortfall priced at the same snapshotted per-unit cost the billing engine uses — no service-fee overlay and no bulk-discount overlay applies to the credit. Resolve then credits `client.credit_balance_cents` by exactly `dispute_credit_cents` and flips the delivery's `status` to `FINALIZED`. The credit-hop on the client is caused by the just-computed `dispute_credit_cents` value and is itself a mutation on the client (which increments `client.version`) — with the exception that when `dispute_credit_cents` is exactly zero (every line's `actual_units` equals its `planned_units`), the client hop is skipped entirely and `client.version` is not bumped, since a zero-value credit is not a mutation of the client's ledger.

If no dispute is filed and the 48-hour window closes, the platform admin **auto-finalizes** the delivery. Auto-finalize requires the delivery to be `DELIVERED` and requires the current clock to be at least 48 hours past `delivered_at`. Because no dispute was raised, actuals default to planned, and `final_cents` is set equal to `provisional_cents` under the chronological variant with `actual_units` equal to `planned_units`. No client credit is issued on the auto-finalize path.

Deliveries caught by the pause/cancel cascade of §2.7 follow different rules. A `SCHEDULED` delivery cancelled by the cascade transitions directly to `CANCELLED` with no charge and no credit — it never left the depot. An `EN_ROUTE` delivery cancelled by the cascade transitions to `CANCELLED`, but as it had already been dispatched with a `provisional_cents` charge, the cascade computes `dispute_credit_cents` equal to that `provisional_cents` and credits `client.credit_balance_cents` by that amount — this is the courtesy-credit hop 4 of §2.7. `DELIVERED`, `DISPUTED`, and previously `FINALIZED` deliveries are not touched by the cascade.

### 3.7. Rotation Close and Invoicing

Once a rotation cycle's window has elapsed and every delivery under the cycle is in a terminal state (`FINALIZED` or `CANCELLED`), a platform admin **closes** the cycle. Close requires the cycle to be `OPEN`, requires every delivery under the cycle to be `FINALIZED` or `CANCELLED`, requires the current clock to be at least `effective_to` on the cycle, and requires the parent subscription's `status` to be either `ACTIVE` or `PAUSED` — a `CANCELLED` subscription's cycle cannot be closed (though it would have been `INVALIDATED` anyway, and `INVALIDATED` cycles are not eligible to close).

Close performs a single atomic operation that flips the cycle's `status` from `OPEN` to `CLOSED` and creates an **Invoice**. The invoice binds to the client via `client_id` and to the cycle via `rotation_cycle_id`; its `period_start` is copied from the cycle's `effective_from` and its `period_end` is copied from `effective_to`. The billing engine then fills four computed monetary fields on the invoice.

**Subscription fee.** The subscription-fee calculation reads the plan snapshot referenced by `subscription.plan_id` at `subscription.plan_version_snapshot` and the client's `headcount` as of the moment the cycle closes. There are two branches on `billing_type`:

- Under `FLAT` billing, `subscription_fee_cents` equals `plan.flat_fee_cents`. No headcount computation, no volume discount.
- Under `PER_EMPLOYEE` billing, the engine first computes the raw per-employee amount as `per_employee_fee_cents` multiplied by `headcount`. If the client's `headcount` is at least the plan's `volume_discount_threshold_headcount` (the boundary is inclusive), the raw amount is multiplied by one minus `volume_discount_pct` to yield a discounted amount; that discounted amount is then rounded to integer cents using round-half-up. If `headcount` is strictly less than the threshold, no discount is applied and the raw per-employee amount is used as-is. The rounded (or unrounded) per-employee amount is then added to `plan.base_fee_cents` to produce `subscription_fee_cents`. The rounding step happens once, after the discount and before the base-fee addition — the specification rejects orderings that sum discounted per-employee and base fee before rounding.

**Consumption.** The consumption calculation is a straight aggregation: `consumption_cents` is the sum of `delivery.final_cents` across all deliveries under the cycle whose `status` is `FINALIZED`. `CANCELLED` deliveries are excluded — their provisional charge was computed but never realized — and deliveries in `SCHEDULED`, `EN_ROUTE`, `DELIVERED`, or `DISPUTED` cannot exist at close time because the state precondition would already have blocked the close.

**Credit application.** `credit_applied_cents` is `min(client.credit_balance_cents, subscription_fee_cents + consumption_cents)`; that is, the invoice consumes as much of the client's running credit as the invoice's chargeable subtotal can absorb, but no more. The client's `credit_balance_cents` is then decremented by the same amount, ensuring credit is not double-consumed by a later invoice.

**Total.** `total_cents` is `subscription_fee_cents + consumption_cents - credit_applied_cents` — always non-negative given the min cap on credit.

The invoice's `payment_status` is `UNPAID` on creation and its `dispute_status` is `CLEAN` on creation. These two enumerations move on independent dimensions: `payment_status` cycles among `UNPAID`, `PAID`, and `DEFAULT`, while `dispute_status` cycles among `CLEAN`, `UNDER_DISPUTE`, and `RESOLVED`. Payment does not disturb dispute state and vice versa.

**Paying.** The client admin marks an invoice paid by moving `payment_status` from `UNPAID` to `PAID`. Payment requires `payment_status` to be `UNPAID`, requires `dispute_status` to be `CLEAN` or `RESOLVED` (an `UNDER_DISPUTE` invoice cannot be paid — `ERR_INVOICE_UNDER_DISPUTE`), and requires the admin's `X-User-ID` to match the invoice's `client_id`.

**Overdue sweep.** A platform admin can drive the logical clock forward for test scenarios (a capability that sets the server's clock to a supplied `to_iso8601` instant) and then invoke an admin-only sweep that walks every invoice, and for each invoice whose `payment_status` is `UNPAID` and whose current clock is at least 30 days past `period_end`, flips `payment_status` from `UNPAID` to `DEFAULT`. Every affected invoice's `version` is incremented. The default server clock at startup, before any clock-set call, is `2026-03-01T00:00:00Z`.

**Invoice dispute resolution.** An `UNDER_DISPUTE` invoice — flagged in the pause cascade of §2.7 — is walked back to `RESOLVED` by a platform admin. Resolution touches only the `dispute_status` dimension and leaves `payment_status` unchanged; a `RESOLVED` invoice may then be paid or, if the 30-day window has already elapsed, defaulted by the next sweep.

### 3.8. Feedback and Satisfaction

Employees at a client office give feedback through their client admin. A **Feedback** submission binds to a `product_id`, carries an integer `rating` from 1 through 5 inclusive, and may include a free-text `comment` and an optional `swap_suggestion_product_id`. When the suggestion is supplied and the `rating` is at most 2, the suggested product becomes a swap candidate on the next rotation's assortment. A suggestion that points at a product the client's preference blocks is rejected with `ERR_DIETARY_PREFERENCE_VIOLATION` — the priority-ordered dietary check of §2.11 catches both par-level creation and feedback swap suggestions.

Feedback is append-only; it carries only `id` and `created_at` and has no `updated_at` or `version` (§2.4).

A satisfaction score is derived from the feedback stream. The computation runs in two variants that share a common weighted-average shape but differ in what feedback rows they consider. The **provisional variant** — used for internal audit and churn analysis — counts every feedback row ever recorded for the client, including feedback about products that are no longer stocked at any of the client's locations. The **authoritative variant** — the default surface for a public satisfaction query — counts only feedback whose `product_id` currently appears in a `ParLevel` under one of the client's locations, silently excluding stale feedback that referred to products long dropped from the assortment. The same client and the same feedback rows can produce different scores under the two variants because the denominator differs.

For both variants, the weighting rewards actionable feedback: a row with a non-null `swap_suggestion_product_id` counts with weight 2, and a row with a null suggestion counts with weight 1. The formula sums each row's `rating` multiplied by its weight to produce the numerator, sums the weights alone to produce the denominator, divides, and rounds half-up to two decimal places. If the filtered set for a variant is empty (no rows at all in provisional, or no rows referencing currently-stocked products in authoritative), the score is the neutral default of 3.00. The satisfaction endpoint returns a response body with four fields: `client_id`, `variant` (the variant that was used), `score` (the fixed-point two-decimal number), and `feedback_considered` (the size of the filtered set that fed the average). Callers may control the variant via a `variant` query parameter; when omitted, the endpoint returns the authoritative variant.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`; operations that modify or retrieve an existing resource return `200 OK`. The overdue-invoice sweep and the clock-set capability also return `200 OK`. Refer back to §3 for request-body semantics, computed-field mechanics, and side-effect cascades — the summary table below intentionally omits per-endpoint request and response detail.

| Method | Path                                             | Description                                                             | Authorized Role(s)                              |
| ------ | ------------------------------------------------ | ----------------------------------------------------------------------- | ----------------------------------------------- |
| POST   | `/plans`                                         | Create a Plan.                                                          | PlatformAdmin                                   |
| GET    | `/plans`                                         | List Plans.                                                             | PlatformAdmin, ClientAdmin                      |
| GET    | `/plans/{id}`                                    | Retrieve a Plan.                                                        | PlatformAdmin, ClientAdmin                      |
| POST   | `/products`                                      | Create a Product.                                                       | PlatformAdmin                                   |
| GET    | `/products`                                      | List Products (filter by `category`).                                   | PlatformAdmin, ClientAdmin, LocationManager     |
| GET    | `/products/{id}`                                 | Retrieve a Product.                                                     | PlatformAdmin, ClientAdmin, LocationManager     |
| POST   | `/clients`                                       | Create a Client (office).                                               | PlatformAdmin                                   |
| GET    | `/clients/{id}`                                  | Retrieve a Client.                                                      | PlatformAdmin, ClientAdmin                      |
| PATCH  | `/clients/{id}/headcount`                        | Adjust the client's headcount.                                          | PlatformAdmin                                   |
| POST   | `/clients/{id}/locations`                        | Declare a Location at the office.                                       | ClientAdmin                                     |
| GET    | `/clients/{id}/locations`                        | List Locations for a client.                                            | PlatformAdmin, ClientAdmin                      |
| GET    | `/locations`                                     | List Locations across the platform (filter by `client_id`).             | PlatformAdmin                                   |
| GET    | `/locations/{id}`                                | Retrieve a Location.                                                    | PlatformAdmin, ClientAdmin, LocationManager     |
| POST   | `/clients/{id}/preferences`                      | Declare a dietary preference block.                                     | ClientAdmin                                     |
| GET    | `/clients/{id}/preferences`                      | List Preferences for a client.                                          | PlatformAdmin, ClientAdmin                      |
| POST   | `/locations/{id}/par-levels`                     | Set a ParLevel for a (location, product).                               | LocationManager                                 |
| GET    | `/locations/{id}/par-levels`                     | List ParLevels for a Location.                                          | PlatformAdmin, ClientAdmin, LocationManager     |
| GET    | `/par-levels/{id}`                               | Retrieve a ParLevel.                                                    | PlatformAdmin, ClientAdmin, LocationManager     |
| GET    | `/par-levels`                                    | List all ParLevels (filter by `location_id` or `product_id`).           | PlatformAdmin                                   |
| POST   | `/clients/{id}/subscriptions`                    | Create a Subscription (OCC on `expected_client_version`).               | ClientAdmin                                     |
| GET    | `/subscriptions`                                 | List Subscriptions (filter by `client_id` or `plan_id`).                | PlatformAdmin, ClientAdmin                      |
| GET    | `/subscriptions/{id}`                            | Retrieve a Subscription.                                                | PlatformAdmin, ClientAdmin                      |
| POST   | `/subscriptions/{id}/activate`                   | Activate a DRAFT Subscription; opens the first rotation.                | PlatformAdmin                                   |
| POST   | `/subscriptions/{id}/pause`                      | Pause an ACTIVE Subscription; triggers the depth-3+ cascade.            | ClientAdmin                                     |
| POST   | `/subscriptions/{id}/resume`                     | Resume a PAUSED Subscription; opens a new rotation.                     | ClientAdmin                                     |
| POST   | `/subscriptions/{id}/cancel`                     | Cancel a Subscription (from ACTIVE or PAUSED).                          | ClientAdmin                                     |
| GET    | `/subscriptions/{id}/rotation-cycles`            | List RotationCycles for a Subscription.                                 | PlatformAdmin, ClientAdmin                      |
| GET    | `/rotation-cycles/{id}`                          | Retrieve a RotationCycle.                                               | PlatformAdmin, ClientAdmin                      |
| POST   | `/rotation-cycles/{id}/close`                    | Close an OPEN RotationCycle; creates the Invoice.                       | PlatformAdmin                                   |
| POST   | `/rotation-cycles/{id}/deliveries`               | Generate a Delivery under a rotation.                                   | PlatformAdmin                                   |
| GET    | `/rotation-cycles/{id}/deliveries`               | List Deliveries under a RotationCycle.                                  | PlatformAdmin, ClientAdmin, LocationManager     |
| GET    | `/deliveries`                                    | List Deliveries (filter by `location_id` or `rotation_cycle_id`).       | PlatformAdmin                                   |
| GET    | `/deliveries/{id}`                               | Retrieve a Delivery.                                                    | PlatformAdmin, ClientAdmin, LocationManager     |
| POST   | `/deliveries/{id}/dispatch`                      | Dispatch a SCHEDULED Delivery (writes `provisional_cents`).             | PlatformAdmin                                   |
| POST   | `/deliveries/{id}/confirm`                       | Confirm an EN_ROUTE Delivery arrived (stamps `delivered_at`).           | LocationManager                                 |
| POST   | `/deliveries/{id}/dispute`                       | File a dispute on a DELIVERED Delivery.                                 | LocationManager                                 |
| POST   | `/deliveries/{id}/resolve-dispute`               | Resolve a dispute; credits the client for shortfall.                    | PlatformAdmin                                   |
| POST   | `/deliveries/{id}/finalize`                      | Auto-finalize a DELIVERED Delivery after 48 hours.                      | PlatformAdmin                                   |
| GET    | `/deliveries/{id}/lines`                         | List DeliveryLines for a Delivery.                                      | PlatformAdmin, ClientAdmin, LocationManager     |
| GET    | `/delivery-lines/{id}`                           | Retrieve a DeliveryLine.                                                | PlatformAdmin, LocationManager                  |
| GET    | `/delivery-lines`                                | List DeliveryLines (filter by `delivery_id` or `product_id`).           | PlatformAdmin, LocationManager                  |
| PATCH  | `/delivery-lines/{id}/actual`                    | Report `actual_units` for a DeliveryLine.                               | LocationManager                                 |
| GET    | `/invoices`                                      | List Invoices (filter by `rotation_cycle_id`).                          | PlatformAdmin                                   |
| GET    | `/invoices/{id}`                                 | Retrieve an Invoice.                                                    | PlatformAdmin, ClientAdmin                      |
| GET    | `/clients/{id}/invoices`                         | List Invoices for a client.                                             | PlatformAdmin, ClientAdmin                      |
| POST   | `/invoices/{id}/pay`                             | Pay an UNPAID Invoice.                                                  | ClientAdmin                                     |
| POST   | `/invoices/{id}/resolve-dispute`                 | Resolve an Invoice dispute (dispute_status UNDER_DISPUTE -> RESOLVED).  | PlatformAdmin                                   |
| POST   | `/clients/{id}/feedback`                         | Submit Feedback (may include `swap_suggestion_product_id`).             | ClientAdmin                                     |
| GET    | `/clients/{id}/feedback`                         | List Feedback for a client (filter by `product_id`).                    | PlatformAdmin, ClientAdmin                      |
| GET    | `/feedback`                                      | Platform-wide feedback listing (filter by `client_id`, `product_id`, `swap_suggestion_product_id`). | PlatformAdmin        |
| GET    | `/feedback/{id}`                                 | Retrieve a Feedback record.                                             | PlatformAdmin, ClientAdmin                      |
| GET    | `/clients/{id}/satisfaction`                     | Compute a client satisfaction score (`variant` query parameter).        | PlatformAdmin, ClientAdmin                      |
| POST   | `/_clock/set_current_utc`                        | Test-driving capability: set the server's logical clock to `to_iso8601`.| PlatformAdmin                                   |
| POST   | `/_system/advance-invoice-default`               | Test-driving capability: run the overdue-invoice sweep.                 | PlatformAdmin                                   |

## 5. Error Code Catalogue

| Error ID                              | HTTP Status Code       |
| ------------------------------------- | ---------------------- |
| `ERR_MISSING_AUTH_HEADERS`            | 401 Unauthorized       |
| `ERR_UNAUTHORIZED`                    | 403 Forbidden          |
| `ERR_FORBIDDEN_OWNERSHIP`             | 403 Forbidden          |
| `ERR_CLIENT_NOT_FOUND`                | 404 Not Found          |
| `ERR_LOCATION_NOT_FOUND`              | 404 Not Found          |
| `ERR_PRODUCT_NOT_FOUND`               | 404 Not Found          |
| `ERR_PLAN_NOT_FOUND`                  | 404 Not Found          |
| `ERR_SUBSCRIPTION_NOT_FOUND`          | 404 Not Found          |
| `ERR_DELIVERY_NOT_FOUND`              | 404 Not Found          |
| `ERR_ROTATION_CYCLE_NOT_FOUND`        | 404 Not Found          |
| `ERR_INVOICE_NOT_FOUND`               | 404 Not Found          |
| `ERR_DELIVERY_LINE_NOT_FOUND`         | 404 Not Found          |
| `ERR_INVALID_STATE`                   | 409 Conflict           |
| `ERR_SUBSCRIPTION_NOT_ACTIVE`         | 409 Conflict           |
| `ERR_INVOICE_UNDER_DISPUTE`           | 409 Conflict           |
| `ERR_DIETARY_PREFERENCE_VIOLATION`    | 422 Unprocessable Entity |
| `ERR_REFRIGERATION_MISMATCH`          | 422 Unprocessable Entity |
| `ERR_LOCATION_CAPACITY_EXCEEDED`      | 422 Unprocessable Entity |
| `ERR_DELIVERY_SCHEDULE_CONFLICT`      | 409 Conflict           |
| `ERR_ROTATION_CYCLE_OVERLAP`          | 422 Unprocessable Entity |
| `ERR_SUBSCRIPTION_ALREADY_ACTIVE`     | 409 Conflict           |
| `ERR_EMPTY_ASSORTMENT`                | 422 Unprocessable Entity |
| `ERR_INVALID_HEADCOUNT`               | 422 Unprocessable Entity |
| `ERR_STALE_CLIENT_VERSION`            | 412 Precondition Failed |
| `ERR_INVALID_REQUEST`                 | 400 Bad Request        |
