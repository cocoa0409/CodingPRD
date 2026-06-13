# Custom Bakery & Cake Orders API — Product Requirements Document

## 1. Introduction

This document specifies the Custom Bakery & Cake Orders API, the backbone of an artisan bakery that takes bespoke, made-to-order cakes from a customer's first sketch all the way through baking, pickup, and delivery. The business problem this system solves is fundamentally one of orchestration under temporal pressure: a custom cake cannot be produced on a whim. It must respect each product's lead time, the bakery's daily oven capacity, hard order cutoffs that protect the production floor, and the design back-and-forth between the bakery and the customer before any flour is committed.

The API models a single Order as the central aggregate, carrying two independent status axes that evolve on their own timelines — one tracking the *production lifecycle* (from a tentative draft, through design-proof approval, into the oven, and out for fulfillment) and the other tracking the *payment ledger* (an upfront deposit followed by a final balance settlement that may draw on store credit). Around that aggregate sit configuration peers — the product catalog, customization options, the capacity calendar of production days, and delivery routes — plus the customers who own their orders. Pricing is deliberately two-phase: a provisional estimate that floats while the customer is still editing, and a locked final total snapped at the moment a design proof is approved.

The remainder of this document defines the system-wide contracts every endpoint honors (Section 2), the detailed business workflows and the rules scattered across them (Section 3), the endpoint catalogue (Section 4), and the canonical error codes (Section 5). Section 3 is the authoritative source for *how* each operation behaves; the endpoint table in Section 4 is intentionally terse and must be read together with the narratives.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, formats, and cross-cutting principles that hold across the entire API.

### 2.1. User and Role-Based Access Control

Every request other than anonymous customer self-registration must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the caller acts. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes five roles, spelled exactly as follows: `Anonymous`, `Customer`, `BakeryStaff`, `DeliveryDispatcher`, and `BakeryManager`.

- `Anonymous` is an unauthenticated caller. Its only capability is to self-register as a customer; it presents no `X-User-ID` tied to a persisted entity and is never compared against any resource ownership.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. Concretely, for any customer-owned action under an order, the order's `customer_id` must equal the caller's `X-User-ID`; a mismatch is rejected with `ERR_NOT_ORDER_OWNER`.
- When `X-User-Role` is `BakeryStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. `BakeryStaff` runs the production floor — posting proofs and advancing the bake lifecycle.
- When `X-User-Role` is `DeliveryDispatcher`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. `DeliveryDispatcher` owns route registration and the commit/release of slot reservations.
- When `X-User-Role` is `BakeryManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to an entity `id`. `BakeryManager` configures the catalog, customization options, the production calendar, and routes; grants or debits store credit; mints lead-time/cutoff overrides; and operates the test clock.

Role authorization is evaluated before ownership: an entirely disallowed role is rejected with `ERR_FORBIDDEN_ROLE`, and only for a role that *is* permitted as a customer-owned action does the system then check that `X-User-ID` matches the order's `customer_id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these bounds is rejected with `ERR_VALIDATION_PAGINATION`.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination bookkeeping in the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in this system carry a standard set of server-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp, with the same format, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation. It underpins optimistic concurrency control (Section 2.7).

The catalog and operational entities — `ProductCatalogItem`, `CustomizationOption`, `ProductionDay`, `DeliveryRoute`, `Customer`, `Order`, `OrderLineCustomization`, `DesignProof`, and `SlotReservation` — all carry the full set above. The one exception is the `Payment` resource: a payment is an immutable ledger entry and therefore carries only `id` and `created_at`. A `Payment` has no `updated_at` and no `version`, and is never mutated after it is recorded.

### 2.5. Hierarchical Consistency and Cascades

The `Order` is the parent aggregate; `OrderLineCustomization`, `DesignProof`, `Payment`, and `SlotReservation` are its children. Many operations mutate more than one entity at once, and every such cascade described in Section 3 is mandatory, not optional.

Whenever an operation changes an order — whether by advancing one of its status axes, recomputing a total, adding or editing a line, or recording a payment — the order's `updated_at` is refreshed and its `version` is incremented by one. The same `updated_at`/`version` discipline applies independently to each mutated child and to cross-aggregate peers: when a slot reservation is committed or released, that reservation's own `version` increments; when a production day's committed unit tally moves, that production day is mutated; when a balance capture touches a customer's credit and loyalty, that customer is mutated.

A single request can ripple across the hierarchy. Committing a delivery slot, for example, advances the reservation, charges units against a production day, *and* increments the parent order's version. Cancelling an order in certain states releases reservations (which in turn decrement a production day's committed units), supersedes outstanding proofs, and settles refunds — all atomically as part of the one cancel operation. These multi-entity effects are spelled out in the relevant Section 3 workflows; the implementer must perform every leg of each cascade.

### 2.6. Nested Resource Retrieval and Path Validation

Many paths nest identifiers — an order id, then a proof id or a reservation id beneath it. For any request whose path carries more than one identifier, the system validates them left-to-right and rejects on the *first* identifier that does not resolve to a row, returning `ERR_NOT_FOUND`. A request for a proof under a non-existent order fails on the order before the proof is ever consulted. This left-to-right rule covers every id-bearing path: orders, proofs, reservations, routes, products, production days, and customers.

Separately, references supplied in a request *body* are checked for existence as well. When a body names a `product_id`, `production_day_id`, `customer_id`, or `route_id` that does not resolve, or names a `selected_option_codes` entry that does not correspond to an existing customization option, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. This body-reference check applies to order creation, line creation, and slot creation.

### 2.7. Optimistic Concurrency Control on Orders

Two write operations are guarded by optimistic concurrency control against the parent `Order`'s `version`, because both can be invalidated by intervening writes that the caller has not observed.

The first is committing a slot reservation. A commit request must carry `expected_order_version` holding the order `version` the dispatcher last read. If the order's `version` has advanced since then — for instance because final pricing landed or another reservation commit already consumed capacity — the commit is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), so the dispatcher re-reads the authoritative order before consuming capacity against a stale view.

The second is capturing the final balance payment. A balance-payment request must carry `expected_order_version` matching the order's current `version`. If final pricing was re-approved or a credit adjustment moved the figures since the customer last read the order, the order's `version` will have advanced and the capture is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), forcing the customer to re-read the authoritative `balance_due_cents` first.

No other endpoint takes a version field; these two are the only OCC-guarded writes, and on both the `expected_order_version` field is required, not optional.

### 2.8. Monetary Precision and Rounding

All money in the system is held as integer cents; there are no fractional cents and no floating-point currency. Where a calculation multiplies a cents amount by a percentage rate — the peak-date surcharge rate steps and the tiered deposit ratio — the product is rounded to the nearest whole cent using the round-half-up convention (a result whose fractional part is exactly one-half rounds up). Capacity arithmetic, by contrast, works in whole units: the peak-day capacity ratio is applied by flooring, as described in Section 3.

### 2.9. Order Status Axes

An `Order` carries two independent status fields that progress on separate timelines. The `production_status` axis tracks the bake lifecycle and takes one of `DRAFT`, `QUOTED`, `PROOF_PENDING`, `CHANGES_REQUESTED`, `PROOF_APPROVED`, `IN_PRODUCTION`, `READY`, `FULFILLED`, or `CANCELLED`; it begins at `DRAFT`, and `FULFILLED` and `CANCELLED` are terminal. The `payment_status` axis tracks the deposit/balance ledger and takes one of `UNPAID`, `DEPOSIT_PAID`, `PAID_IN_FULL`, or `REFUNDED`; it begins at `UNPAID`, and `REFUNDED` is terminal. The two axes advance independently — for instance, an order can be `QUOTED` on the production axis while still `UNPAID`, or `PROOF_APPROVED` while `DEPOSIT_PAID`. Any attempt to drive a transition that is not defined from an entity's current state (on any of the production, payment, proof, or reservation axes) is rejected with `ERR_INVALID_STATE`.

### 2.10. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`); (3) order ownership for customer-owned actions (`ERR_NOT_ORDER_OWNER`); (4) existence of every path id, left-to-right (`ERR_NOT_FOUND`); (5) existence of body references (`ERR_REFERENCE_NOT_FOUND`); (6) that the target transition is legal from the current state (`ERR_INVALID_STATE`); (7) the optimistic-concurrency version check on the two guarded writes (`ERR_STALE_ORDER_VERSION`); and then the business rules — allergen/dietary safety, option allowance, lead time, cutoff, route-window overlap, the proof-approval gate, production-day capacity, credit sufficiency, and payment-amount correctness — as detailed in Section 3. Malformed bodies, missing required fields, bad enum values, and out-of-range numerics (such as a `window_start_min` outside the 0-to-1439 range or `units` below 1) are rejected with `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Configuring the Catalog, Calendar, and Routes

Before any order can exist, a `BakeryManager` configures the shop. A **product** is created with a `name`, a `base_price_cents` charged once per unit (never negative), and a `base_lead_days` count — the minimum number of whole calendar days that must elapse between when an order is placed and the production date for this product (never negative). A product also declares `tier_levels`, the number of stacked tiers, which defaults to 1 and must be at least 1; a product whose `tier_levels` is 3 or more is treated as a *complex bake* that needs a production buffer day. The product lists `allowed_option_codes`, the customization option codes that may be selected against it, and `declared_allergen_codes`, the allergens intrinsically present in the base recipe (for example `EGG`, `DAIRY`, `NUT`, `GLUTEN`). A product's `status` defaults to `ACTIVE` and is one of `ACTIVE` or `RETIRED`.

A **customization option** is created with a unique `option_code`, a flat `surcharge_cents` (never negative) added once per order line that selects it, an `introduces_allergen_codes` array naming allergens the option brings in (selecting `MARZIPAN`, say, introduces `NUT`), and a `dietary_exclusion_codes` array naming dietary tags the option is incompatible with (buttercream excludes `VEGAN`, for example).

The **production calendar** is a set of production days, each registered with a unique `production_date` (an ISO calendar date the row governs), a `unit_capacity` (the maximum order units that may bake that day, never negative), an `is_peak` flag (defaulting to false) that, when true, both triggers a peak surcharge and tightens the capacity ratio, and an `order_cutoff_at` — an ISO 8601 UTC timestamp after which no new order may bind that date unless a manager override is supplied. The running tally `units_committed` starts at 0 and is recomputed on every reservation commit or release against the date; it is server-maintained, not client-supplied.

A **delivery route** is registered with a `route_name` label, a `service_date` (the ISO calendar date the route runs), and a `stop_minutes` value (at least 1) — the number of minutes each delivery occupies the route window, measured forward from a reservation's window start.

### 3.2. Customers, Store Credit, and Loyalty

Anyone may self-register as a **customer** by supplying an `email` (unique across customers) and a `full_name`; a `BakeryManager` may also create customers. A customer record additionally tracks two server-computed money/loyalty fields. `store_credit_cents` is the refundable store-credit balance in cents, starting at 0; it is debited when a customer elects to apply credit to an order balance and credited when a cancellation refund is routed to credit. `lifetime_spend_cents`, also starting at 0, accumulates the cents of captured payments across all of the customer's orders and drives the loyalty tier. The derived `loyalty_tier` is one of `STANDARD`, `SILVER`, or `GOLD`, defaulting to `STANDARD`: a customer is `STANDARD` while `lifetime_spend_cents` is below 50000, `SILVER` while it is from 50000 through 149999 inclusive, and `GOLD` once it reaches 150000 or more.

A `BakeryManager` operating the admin surface may directly adjust a customer's store credit by submitting a `delta_cents` amount with an optional `reason`. The adjustment adds `delta_cents` to `store_credit_cents` (a negative delta debits it) and increments that customer's `version` by one. This is the operator-facing path to grant or claw back credit outside the refund machinery.

### 3.3. Order Creation and the Draft Line Set

A `Customer` opens an order by binding it to a product, a production day, and themselves: the create payload supplies `customer_id`, `product_id`, and `production_day_id`. On creation the server freezes `placed_at` to the current time, sets `production_status` to `DRAFT`, and sets `payment_status` to `UNPAID`. The `placed_at` timestamp is what every later lead-time and cutoff check reads, so it is captured once at creation and never moves.

While an order is in an editable production state — `DRAFT`, `QUOTED`, or `CHANGES_REQUESTED` — the customer composes its **lines**. Each `OrderLineCustomization` carries the `order_id` it belongs to, a `units` count (the number of bakeable units this line represents, at least 1), a `selected_option_codes` array of option codes applied to the line, and a `requested_dietary_codes` array of dietary tags the customer requires for the line (such as `VEGAN` or `GLUTEN_FREE`). Two line fields are computed by the server whenever the line changes. `line_surcharge_cents` is the sum of `surcharge_cents` across the line's selected options, multiplied by the line's `units`. `effective_allergen_codes` is the union of the product's `declared_allergen_codes` with the `introduces_allergen_codes` of every selected option.

Two business checks guard line creation and line edits. First, every entry in `selected_option_codes` must appear in the product's `allowed_option_codes`; an option the product does not permit is rejected with `ERR_OPTION_NOT_ALLOWED`. Second, the dietary safety check described in Section 3.4 must pass. A line may be edited (changing any of `units`, `selected_option_codes`, or `requested_dietary_codes`) or deleted only while the order is in one of the editable states above; once the order has advanced past proof approval the lines are frozen, and any add, edit, or delete attempt is rejected with `ERR_LINE_IMMUTABLE`. When a line is added, edited, or removed while the order is `QUOTED`, the estimate and deposit are recomputed (see Section 3.5); deleting a line while `QUOTED` likewise re-runs the estimate. Each of these line mutations increments the order's `version`.

### 3.4. Dietary and Allergen Safety

The bakery will not knowingly bake a cake that violates a customer's dietary requirement, so every line is checked for internal consistency at creation and on edit. The check has two parts, and both must hold. First, none of the line's `requested_dietary_codes` may be contradicted by the `dietary_exclusion_codes` of any option the line selects — if a requested tag is listed as excluded by a chosen option, the combination is illegal. Second, the line's computed `effective_allergen_codes` must not contain an allergen that a requested dietary tag forbids; for example a `VEGAN` requirement forbids `DAIRY` and `EGG`, and a `GLUTEN_FREE` requirement forbids `GLUTEN`. If either part fails, the line operation is rejected with `ERR_DIETARY_CONFLICT`. This dietary check guards both line creation and line editing.

### 3.5. Quoting: Estimate, Deposit, and Balance

When the customer is satisfied with the draft, they request a **quote**, which locks the current line set into a provisional price and moves `production_status` from `DRAFT` to `QUOTED`. Quoting is only permitted once the order has at least one line. It also enforces the two temporal gates described in Section 3.6. Quoting runs the estimate pricing pipeline, runs the deposit calculation, and sets the balance, then increments the order's `version`. An optional `manager_override_token` may accompany the quote to waive the temporal gates.

**Estimate pricing** computes `estimate_total_cents` from all of the order's lines (lines have no status, so the whole set participates). The pipeline has a pinned evaluation order, because the peak surcharge depends on the lines' subtotal and the grand total depends on the peak surcharge:

1. First, compute the lines subtotal. For each line, take its `units` multiplied by the product's `base_price_cents`, and add the line's `line_surcharge_cents`; sum that across all lines. (The base price is thus charged once per unit, and the option surcharges are already folded into each line's `line_surcharge_cents`.)
2. Next, compute `peak_surcharge_cents`. If the order's production day is not a peak day, the peak surcharge is 0. If it is a peak day, the surcharge is keyed on the subtotal in three tiers: when the subtotal is below 20000 cents the surcharge is a flat 2500 cents; when the subtotal is at least 20000 but below 50000 cents the surcharge is the subtotal multiplied by 0.10, rounded half-up to whole cents; and when the subtotal is 50000 cents or more the surcharge is the subtotal multiplied by 0.15, rounded half-up to whole cents.
3. Finally, `estimate_total_cents` is the lines subtotal plus `peak_surcharge_cents`.

The estimate is provisional: it is recomputed on every line mutation while the order is `DRAFT` or `QUOTED`, and `peak_surcharge_cents` is folded into it.

**The deposit** required to advance toward production is computed by `deposit_calc` off the estimate, and written to `deposit_due_cents`. The deposit ratio interacts across three inputs — the estimate total, whether the production day is a peak day, and the product's tier count. Begin with a base ratio of 0.30. If the production day is a peak day, raise the base ratio to 0.50. If the product is a complex bake (its `tier_levels` is 3 or more), raise the ratio to whichever is larger of the current ratio and 0.60 — so a complex bake always demands at least 60%, and a complex *peak* bake also lands at 0.60. Multiply the estimate total by the resulting ratio and round half-up to whole cents. Then clamp the result: the deposit is never less than the floor of 5000 cents and never more than the estimate total itself (so it is the larger of the rounded amount and 5000, then the smaller of that and the estimate total).

Finally, quoting sets `balance_due_cents` to `estimate_total_cents` minus `deposit_due_cents`. The `applied_credit_cents` field on the order, which records how much store credit the customer elects to apply at balance time, defaults to 0 and never goes negative; it is supplied later, at balance capture.

### 3.6. Lead Time and Order Cutoff

Two temporal gates protect the production floor, and both are checked at quote time. The **lead-time** gate requires that the order's `placed_at` plus the product's `base_lead_days` whole calendar days falls on or before the production day's `production_date` (taken at the start of that date in UTC). If the lead time is not satisfied and no manager override is supplied, the quote is rejected with `ERR_LEAD_TIME_NOT_MET`. The **cutoff** gate requires that the current time be at or before the production day's `order_cutoff_at`; if the cutoff has already passed and no manager override is supplied, the quote is rejected with `ERR_PAST_ORDER_CUTOFF`.

Both gates can be waived together by attaching a valid `manager_override_token` to the quote request. A `BakeryManager` mints such a token out of band by supplying a `scope`; the mint returns the `token` string and its `scope`. To make lead-time and cutoff behavior deterministic, a `BakeryManager` may also set the server's logical clock by supplying a `now_iso8601` instant, after which every reading of the current time returns that instant.

### 3.7. The Deposit Payment

With a quote in hand, the customer settles the deposit. Recording a **deposit payment** carries a `kind` of `DEPOSIT` and advances the payment axis from `UNPAID` to `DEPOSIT_PAID`. It is permitted only while the production status is `QUOTED` and the computed `deposit_due_cents` is greater than zero. The settlement creates a `Payment` whose `kind` is `DEPOSIT` and whose `amount_cents` equals `deposit_due_cents`. A deposit attempt whose implied amount would not equal `deposit_due_cents` — including the degenerate case where there is no positive deposit leg due, or the wrong ledger leg is attempted — is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. Recording the deposit increments the order's `version`.

A `Payment` is one of three kinds — `DEPOSIT`, `BALANCE`, or `REFUND` — and records its settled `amount_cents`, a `credit_applied_cents` portion (the part of a balance covered by store credit rather than fresh tender, defaulting to 0), and a server-stamped `settled_at` timestamp marking when it was recorded.

### 3.8. Design Proofs and the Revision Loop

Once the deposit is captured, the bakery's design work begins. A `BakeryStaff` member posts a **design proof** by supplying an `image_ref` (an opaque reference to the rendered artifact). Posting the first proof requires that the order's payment status be `DEPOSIT_PAID`, and it advances the production status from `QUOTED` to `PROOF_PENDING`. The proof is created with `revision_number` 1 and `proof_status` `AWAITING_REVIEW`. A `DesignProof` also carries the `order_id` it belongs to and an optional `change_note` recorded when the customer asks for changes. Its `proof_status` is one of `AWAITING_REVIEW`, `APPROVED`, `SUPERSEDED`, or `REJECTED`, beginning at `AWAITING_REVIEW`, with `APPROVED` and `SUPERSEDED` terminal.

The customer reviews the awaiting proof and either requests changes or approves it. **Requesting changes** is allowed while the production status is `PROOF_PENDING` and the named proof is itself `AWAITING_REVIEW`; the customer may attach a `change_note`. This moves the named proof's `proof_status` to `REJECTED` and the order's production status from `PROOF_PENDING` to `CHANGES_REQUESTED`, reopening editing, and increments the order's `version`. The customer can then revise the line set (subject to the editability rules of Section 3.3), and a `BakeryStaff` member posts a **subsequent proof**. Posting a subsequent proof is allowed from `CHANGES_REQUESTED` only when the order has no proof currently `AWAITING_REVIEW`; it creates a new `DesignProof` whose `revision_number` is one greater than the highest revision number seen so far on the order, again `AWAITING_REVIEW`, and drives the order back to `PROOF_PENDING`. This forms a cyclic revision loop between `PROOF_PENDING` and `CHANGES_REQUESTED` that can repeat as many times as needed, each pass incrementing the order's `version`.

**Approving a proof** is allowed while the production status is `PROOF_PENDING` and the named proof is `AWAITING_REVIEW`. Approval sets the named proof's `proof_status` to `APPROVED`, drives the order's production status from `PROOF_PENDING` to `PROOF_APPROVED`, and sweeps every other proof on the order that is still `AWAITING_REVIEW` or `REJECTED` to `SUPERSEDED`. At approval the lines become immutable, the final pricing is locked, and the order's `version` increments. Approval is the cross-entity bubble-up point: the proof reaching `APPROVED` is what carries the parent order into `PROOF_APPROVED`.

### 3.9. Final Pricing and Balance Reconciliation

The instant a proof is approved, **final pricing** runs once and freezes. It uses exactly the same pipeline as the estimate — lines subtotal, then the peak surcharge keyed on the subtotal in the same three tiers (flat 2500 cents below 20000, the subtotal times 0.10 rounded half-up from 20000 through just under 50000, the subtotal times 0.15 rounded half-up at 50000 and above), then the grand total — but evaluated against the line set as it stands at the moment of approval, and the result is written once to `final_total_cents` and never recomputed afterward. If the lines were never touched after quoting, the final total equals the estimate total and the delta is zero. If the lines were edited during a `CHANGES_REQUESTED` loop, the final total diverges from the estimate, and from this point the balance is reconciled off the final total, not the stale estimate.

Concretely, approval recomputes `balance_due_cents` as `final_total_cents` minus the sum of the captured deposit amount. (Until approval, `final_total_cents` is unset.) This is the authoritative figure the customer must settle to finish paying.

### 3.10. Balance Capture, Credit Waterfall, and Loyalty

To pay the **balance**, the customer issues a balance capture against a `PROOF_APPROVED` order. The payload carries a `kind` of `BALANCE`, an optional `applied_credit_cents` electing how much store credit to spend, and the required `expected_order_version` for the optimistic-concurrency check of Section 2.7. The balance leg may only be settled while the production status is `PROOF_APPROVED` — attempting to settle the balance, or to start production, before a proof is `APPROVED` is rejected with `ERR_PROOF_NOT_APPROVED` — and while the payment status is `DEPOSIT_PAID`. A successful capture advances the payment status from `DEPOSIT_PAID` to `PAID_IN_FULL`.

The capture allocates the balance as a **waterfall**: store credit fills first, up to a cap, and fresh tender covers the rest. Let the gross balance be the order's `balance_due_cents` (the final total net of the captured deposit). The credit actually applied, `credit_applied_cents`, is the smallest of three quantities: the `applied_credit_cents` the customer elected, the customer's available `store_credit_cents`, and the gross balance. Fresh tender is then the gross balance minus that applied credit, and it is this fresh-tender figure that the `Payment` records as its `amount_cents`, with `credit_applied_cents` recording the credit leg. Before applying, the system enforces that `applied_credit_cents` may not exceed either the customer's `store_credit_cents` or the gross balance; an excess election is rejected with `ERR_INSUFFICIENT_CREDIT`. A balance whose settlement would not cover the full net balance, or that targets the wrong leg, is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`.

Capture then reconciles the customer and the ledger. The applied credit is subtracted from the customer's `store_credit_cents`. The customer's `lifetime_spend_cents` increases by the fresh tender only — store credit spent does not count toward loyalty — and the `loyalty_tier` is recomputed against the thresholds of Section 3.2. When no credit is applied (`applied_credit_cents` is zero), the fresh tender equals the whole gross balance and lifetime spend rises by that full amount; when credit is applied, fresh tender is the gross balance minus the credit applied and lifetime spend rises only by that fresh tender. The order's `balance_due_cents` falls to 0 and its `version` increments.

### 3.11. Reserving and Committing a Fulfillment Slot

Fulfillment is arranged through a **slot reservation**, which a customer or a dispatcher may create on an order. The reservation carries the `order_id`, a `fulfillment_mode` of either `PICKUP` or `DELIVERY`, an optional `route_id`, and an optional `window_start_min`. A `PICKUP` reservation is counter-only and consumes no route window, so it leaves `route_id` null. A `DELIVERY` reservation binds a `DeliveryRoute`: it requires a `route_id` and a `window_start_min` expressed as minutes-from-midnight on the route's service date (valid only in the range 0 through 1439). A new reservation is created in `HELD` status — one of `HELD`, `COMMITTED`, or `RELEASED`, with `RELEASED` terminal — and creating it increments the order's `version`.

A `DeliveryDispatcher` **commits** a held reservation, which is the point where production-day capacity is actually consumed. Commit is gated on several preconditions evaluated in order. The order must be in `PROOF_APPROVED`. The commit must carry `expected_order_version` matching the order's current `version`, or it is refused with `ERR_STALE_ORDER_VERSION` (HTTP 412) per Section 2.7. For a `DELIVERY` reservation, the requested window must not overlap any existing `COMMITTED` reservation on the same route: windows are half-open intervals running from `window_start_min` for `stop_minutes` (that is, `[start, start + stop_minutes)`), so a new window that touches an existing one only at its closing edge does not overlap, while any genuine interior overlap is rejected with `ERR_ROUTE_WINDOW_CONFLICT`. Finally, the production day must have room: committing must not push the day's `units_committed` plus this order's units over the day's effective capacity, or it is rejected with `ERR_PRODUCTION_DAY_FULL`.

A successful commit moves the reservation from `HELD` to `COMMITTED`, adds this order's units to the production day's `units_committed`, increments the reservation's `version`, and increments the order's `version`. When committing a complex bake (a product whose `tier_levels` is 3 or more) pushes that order's buffer day past its block threshold, the buffer-adjacent production day is marked saturated for new complex orders. Releasing a reservation is the dispatcher's compensating action: it moves the reservation to `RELEASED` and increments the reservation's `version`, and if the reservation had been `COMMITTED`, it subtracts this order's units back out of the production day's `units_committed` (a held reservation that was never committed consumed no units, so releasing it changes no tally).

**Effective capacity** depends on the peak flag. On a non-peak day the effective capacity is the day's full `unit_capacity`. On a peak day the bakery reserves a safety margin: the effective capacity is `unit_capacity` multiplied by 0.80 and floored to a whole number of units. A reservation of the order's units is admissible exactly when the day's `units_committed` plus those units is at or below the effective capacity — landing exactly on the effective capacity is admissible, while exceeding it by even one unit is not.

### 3.12. Into Production, Ready, and Fulfilled

Once a proof is approved, the order is paid in full, and a slot is committed, a `BakeryStaff` member starts production. **Starting production** advances the production status from `PROOF_APPROVED` to `IN_PRODUCTION`; it requires that a `COMMITTED` slot reservation exists for the order and that the payment status is `PAID_IN_FULL`. Attempting to start production before a proof is approved is rejected with `ERR_PROOF_NOT_APPROVED`. From there, `BakeryStaff` **marks the order ready**, advancing `IN_PRODUCTION` to `READY`, and then **fulfills** it, advancing `READY` to `FULFILLED`; fulfillment requires the order's `COMMITTED` reservation to exist, and the reservation remains `COMMITTED` through fulfillment. Each of these production transitions increments the order's `version`.

### 3.13. Cancellation and Refund Settlement

A `Customer` may **cancel** an order from any non-terminal production state, optionally recording a `cancel_reason`. Cancellation always drives the production status to `CANCELLED` and increments the order's `version`, but its downstream effects depend on how far the order had progressed.

Cancelling from `DRAFT` simply terminates the order. Cancelling from `QUOTED` runs refund settlement, which finds no captured deposit yet and therefore refunds nothing. Cancelling from any of `PROOF_PENDING`, `CHANGES_REQUESTED`, or `PROOF_APPROVED` performs the full cascade: every `HELD` or `COMMITTED` slot reservation on the order is released to `RELEASED` (and a released *committed* reservation decrements the production day's `units_committed`, which may in turn unblock a buffer-adjacent production day); every non-terminal `DesignProof` is swept to `SUPERSEDED`; and refund settlement runs.

**Refund settlement** decides how much captured tender returns to the customer as store credit, based on the production state at the moment of cancel. Let the captured amount be the sum of `amount_cents` over the order's captured non-refund payments (the deposit and balance legs; refund entries and the credit portion of a balance are excluded). If the cancel happens from `QUOTED`, the refund equals the captured amount — which is zero, since no deposit has been captured. If it happens from `PROOF_PENDING` or `CHANGES_REQUESTED`, the refund again equals the full captured amount: the deposit is returned in full. If it happens from `PROOF_APPROVED`, the late cancel forfeits the deposit portion — the refund is the captured amount minus `deposit_due_cents`, but never less than zero. The resulting refund amount is credited to the customer's `store_credit_cents`. When any capture is reversed, a `Payment` of `kind` `REFUND` is created and the payment status moves to `REFUNDED`.

### 3.14. Reading Orders and Their Children

All four roles with order visibility — `Customer`, `BakeryStaff`, `BakeryManager`, and `DeliveryDispatcher` — can read an individual order, which exposes both status axes and every computed total: `estimate_total_cents`, `final_total_cents`, `deposit_due_cents`, `balance_due_cents`, `applied_credit_cents`, and `peak_surcharge_cents`. Orders can be listed and filtered by `customer_id`, `product_id`, `production_day_id`, `production_status`, and `payment_status`. The children of an order are reachable through their own listings — its customization lines, its proofs, its payments, and its slot reservations — and a route's committed reservations and a production day's bound orders are likewise listable for the operational roles. Customers see their own orders; staff, managers, and dispatchers see across orders per the role matrix in Section 4.

## 4. Endpoint Definitions

Endpoints that create a new, standalone resource (a product, an order, a line, a proof, a deposit or balance payment, a slot reservation, or a minted override) return `201 Created`. Endpoints that modify an existing resource — quoting, approving or rejecting a proof, committing or releasing a slot, advancing production, cancelling, adjusting credit, or setting the clock — return `200 OK`. Line deletion returns `204 No Content`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a base catalog product | BakeryManager |
| GET | `/products/{id}` | Read a product | BakeryManager, BakeryStaff, Customer |
| GET | `/products` | List products | BakeryManager, BakeryStaff, Customer |
| POST | `/options` | Create a customization option | BakeryManager |
| GET | `/options/{id}` | Read an option | BakeryManager, BakeryStaff, Customer |
| GET | `/options` | List options | BakeryManager, BakeryStaff, Customer |
| POST | `/production-days` | Register a production date with capacity, peak flag, and cutoff | BakeryManager |
| GET | `/production-days/{id}` | Read a production day | BakeryManager, BakeryStaff, DeliveryDispatcher, Customer |
| GET | `/production-days` | List production days | BakeryManager, BakeryStaff, DeliveryDispatcher, Customer |
| POST | `/routes` | Register a delivery route for a service date | BakeryManager, DeliveryDispatcher |
| GET | `/routes/{id}` | Read a route | BakeryManager, DeliveryDispatcher, Customer |
| GET | `/routes` | List routes | BakeryManager, DeliveryDispatcher, Customer |
| POST | `/customers` | Register a customer | Anonymous, BakeryManager |
| GET | `/customers/{id}` | Read a customer | Customer, BakeryManager, BakeryStaff |
| POST | `/customers/{id}/credit-adjustments` | Grant or debit store credit | BakeryManager |
| POST | `/orders` | Create a DRAFT order | Customer |
| GET | `/orders/{id}` | Read an order | Customer, BakeryStaff, BakeryManager, DeliveryDispatcher |
| GET | `/orders` | List orders | Customer, BakeryStaff, BakeryManager, DeliveryDispatcher |
| POST | `/orders/{id}/lines` | Add a customization line | Customer |
| GET | `/orders/{id}/lines` | List the order's lines | Customer, BakeryStaff, BakeryManager |
| PATCH | `/orders/{id}/lines/{lid}` | Edit a line | Customer |
| DELETE | `/orders/{id}/lines/{lid}` | Remove a line | Customer |
| POST | `/orders/{id}/quote` | Lock the line set into a quote | Customer |
| POST | `/orders/{id}/cancel` | Cancel the order | Customer |
| POST | `/orders/{id}/proofs` | Post a design proof | BakeryStaff |
| GET | `/orders/{id}/proofs` | List proofs for an order | Customer, BakeryStaff, BakeryManager |
| POST | `/orders/{id}/proofs/{pid}/approve` | Approve a proof; lock final pricing | Customer |
| POST | `/orders/{id}/proofs/{pid}/request-changes` | Request changes; reopen editing | Customer |
| POST | `/orders/{id}/payments` | Record a DEPOSIT payment | Customer |
| POST | `/orders/{id}/balance-payment` | Capture the BALANCE (OCC-guarded) | Customer |
| GET | `/orders/{id}/payments` | List payments for an order | Customer, BakeryStaff, BakeryManager |
| POST | `/orders/{id}/slot` | Create a HELD slot reservation | Customer, DeliveryDispatcher |
| GET | `/orders/{id}/slot` | List slot reservations for an order | Customer, DeliveryDispatcher, BakeryStaff, BakeryManager |
| POST | `/orders/{id}/slot/{rid}/commit` | Commit a held reservation (OCC-guarded) | DeliveryDispatcher |
| POST | `/orders/{id}/slot/{rid}/release` | Release a held/committed reservation | DeliveryDispatcher |
| GET | `/routes/{id}/reservations` | List committed reservations on a route | DeliveryDispatcher, BakeryManager |
| POST | `/orders/{id}/start-production` | Advance an approved, paid order into production | BakeryStaff |
| POST | `/orders/{id}/mark-ready` | Mark an in-production order ready | BakeryStaff |
| POST | `/orders/{id}/fulfill` | Fulfill a ready order | BakeryStaff |
| GET | `/production-days/{id}/orders` | List orders bound to a production day | BakeryStaff, BakeryManager, DeliveryDispatcher |
| POST | `/_clock/set` | Set the server's current UTC clock (test-only) | BakeryManager |
| POST | `/_overrides/mint` | Mint a lead-time/cutoff override token (test-only) | BakeryManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_ORDER_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_DIETARY_CONFLICT` | 422 Unprocessable Entity |
| `ERR_OPTION_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_LEAD_TIME_NOT_MET` | 422 Unprocessable Entity |
| `ERR_PAST_ORDER_CUTOFF` | 422 Unprocessable Entity |
| `ERR_ROUTE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_PROOF_NOT_APPROVED` | 409 Conflict |
| `ERR_PRODUCTION_DAY_FULL` | 409 Conflict |
| `ERR_INSUFFICIENT_CREDIT` | 422 Unprocessable Entity |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LINE_IMMUTABLE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VALIDATION_PAGINATION` | 400 Bad Request |
