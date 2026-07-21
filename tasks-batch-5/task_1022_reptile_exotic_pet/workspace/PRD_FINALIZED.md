# Reptile & Exotic-Pet Store API — Product Requirements Document

## 1. Introduction

The Reptile & Exotic-Pet Store API is the operational backbone for a specialty livestock retailer that sells live reptiles and exotic animals alongside the husbandry goods that keep them alive. Running such a store means holding several very different responsibilities in balance at once: incoming animals must clear a veterinary quarantine before they can ever be offered for sale; regulated species may not leave the building without a verified government permit; every animal carries a livestock warranty that can turn into a refund, store credit, or a replacement animal if it dies young; and a steady stream of feeder insects and rodents must be received, priced, allocated to recurring subscription shipments, and — when a bad batch surfaces — recalled with all the financial unwinding that implies.

This document specifies the complete contract for that system: the entities the store tracks, the state machines that govern their lifecycles, the pricing and refund arithmetic that must be reproduced to the cent, and the compliance and safety controls (permit gating, quarantine clearance thresholds, and four-eyes segregation-of-duties on recalls and warranty approvals) that protect both the animals and the business. It is written for the engineers building the service, and it is intended to be read as the single, authoritative source of behavior — every rule an implementer needs is stated here, in prose, rather than assumed from domain knowledge. The store additionally runs custom habitat builds and appears at weekend expos, and both of those workflows are folded into the same permissioning, pagination, and consistency model as the rest of the API.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header (or carrying a blank value) is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `StoreManager`, `VetTech`, `SalesAssociate`, and `Customer`.

- A `StoreManager` is a store operator responsible for the species catalogue, animal intake, permit verification and revocation, warranty adjudication, feeder inventory, recalls, expos, and advancing the logical clock. When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `acquired_by_user_id` on an `Animal` at intake, as `verified_by_user_id` on a `Permit`, as `approved_by_user_id` on a `WarrantyClaim`, or as `opened_by_user_id` / `closed_by_user_id` on a `Recall` — but it never compares that identifier to any entity's `id`.
- A `VetTech` is a veterinary technician who owns the quarantine and health lifecycle. When `X-User-Role` is `VetTech`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may stamp it onto a health-check entry as `vet_user_id` but does not compare it to any entity's `id`.
- A `SalesAssociate` works the floor: the sale lifecycle, expo assignments, feeder shipments, and habitat-build execution. When `X-User-Role` is `SalesAssociate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `created_by_user_id` on a `Sale`) but does not compare it to any entity's `id`.
- A `Customer` is an end customer acting on their own resources. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare that resource's `customer_id` (or, transitively, the `customer_id` of the sale a warranty claim is filed against) to `X-User-ID`.

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

Every endpoint that returns a list of resources is paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and any supplied value must be at least 1 and at most 100. The `offset` parameter is the number of leading items to skip; when omitted it defaults to 0, and any supplied value must be at least 0. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order (oldest first). Every list response echoes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the count of all matching records before the limit/offset window is applied and `has_more` is true exactly when records remain beyond the current window.

### 2.4. Common Resource Properties

Every persisted entity in this system — Species, Animal, QuarantineRecord, Customer, Permit, Sale, WarrantyClaim, FeederBatch, FeederSubscription, Shipment, HabitatBuild, Expo, ExpoAssignment, and Recall — carries a common set of system-managed fields:

- `id`: a server-minted UUID string with no type prefix, unique across the system.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at`: an ISO 8601 UTC timestamp, in the same format, recording the last modification to the resource. It is refreshed on every mutation.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation of the resource. It underpins the optimistic-concurrency mechanism described in §2.10.

Whenever a derived or system field changes on a resource — for example when a sale's `sale_price_cents` is pinned at confirmation, when an animal's `status` reconciles as a downstream effect of a quarantine clearance, or when a customer's `wallet_credit_cents` grows from a refund — that change is a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. The Logical Clock

All date, window, expiry, and warranty comparisons in this system are evaluated against a single server-managed **logical clock**, never against wall-clock time. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any call is made it holds precisely that default; it never silently falls back to real time. A `StoreManager` may advance the clock through an admin-only, test-driving capability that sets the current instant to a supplied `to_iso8601` value. Advancing the clock changes the instant that every subsequent quarantine-clearance, permit-expiry, warranty-window, batch-expiry, expo-overlap, and install-buffer rule reads.

### 2.6. Monetary Values, Precision, and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation multiplies a base amount by a percentage or a multiplier — regulated surcharges, loyalty and expo discounts, feeder size multipliers, warranty proration, and habitat deposits — the result of each such multiplication is rounded to a whole number of cents using the **round half up** rule (a fractional cent of exactly one-half rounds up). The specific rounding boundaries matter: in the feeder shipment calculation the rounding is applied to each per-batch unit price *before* it is multiplied by that batch's quantity and *before* the lines are summed (round-per-line, then sum — never sum-then-round). All other intermediate additions and subtractions of already-integer cent amounts are exact.

### 2.7. Hierarchical Consistency and Cascading Effects

Many operations in this system mutate more than one resource. When that happens, the system performs every downstream reconciliation as part of the same operation, and each affected resource independently has its `updated_at` refreshed and its `version` incremented. A parent state change may drive child state changes (closing an expo ends all of its standing assignments; revoking a permit voids the confirmed sales that cite it and releases their animals), and a child state change may bubble up to its parent (clearing a quarantine record makes its animal sellable). The detailed cascade for each workflow is specified in §3; the governing principle is that the system never leaves a partially reconciled state — if an operation's preconditions hold, all of its declared side effects are applied together.

### 2.8. Nested Resource Retrieval and Validation Ordering

Requests are validated in a fixed order so that failures are reported consistently. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization for the operation (`ERR_UNAUTHORIZED`), then — for list endpoints — pagination bounds (`ERR_INVALID_PAGINATION`). Next, the existence of every resource referenced in the path or body is checked left-to-right; the first unresolved reference produces the most specific applicable not-found error (for example `ERR_SPECIES_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_QUARANTINE_NOT_FOUND`, `ERR_FEEDER_BATCH_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_HABITAT_BUILD_NOT_FOUND`, `ERR_EXPO_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, or `ERR_RECALL_NOT_FOUND`), falling back to the generic `ERR_NOT_FOUND` when no specific code fits. Only then are body fields validated for presence, type, and legal enum values (`ERR_VALIDATION`), followed by state-transition legality (`ERR_INVALID_STATE` or its more specific siblings), and finally the operation's business rules. Where a nested path names several identifiers, the outermost (leftmost) resource is resolved before any inner one.

### 2.9. Segregation of Duties (Four-Eyes Controls)

Two operations enforce a four-eyes control in which the same operator may not stand on both sides of a decision. When a `StoreManager` closes a recall, their `X-User-ID` must differ from the `opened_by_user_id` that was stamped when the recall was opened. When a `StoreManager` approves a warranty claim, their `X-User-ID` must differ from the `acquired_by_user_id` recorded on the claimed animal at intake. A violation of either control is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 2.10. Optimistic Concurrency Control

One write in this system is guarded by optimistic concurrency: filing a change order against a habitat build. That request must carry a non-optional `expected_habitat_build_version` field holding the client's last-observed `version` of the target habitat build. Because a change order supersedes the running quote by adding its delta to the build's accumulated change-order total, a client whose view of the build has gone stale — because another change order has already advanced the build's `version` since it was last read — must not be allowed to stack a new delta onto a total it never saw. If `expected_habitat_build_version` does not equal the build's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. The Species Catalogue and Care-Sheets

Everything the store sells begins with a **species** entry, created by a `StoreManager`. A species record combines commercial and husbandry data: a `common_name` (for example, "Ball Python") and a binomial `scientific_name`, whether the species is regulated via `is_regulated` (defaulting to not regulated) and, if so, its `permit_class`. The `permit_class` defaults to `NONE` and must be one of `NONE`, `CLASS_I`, `CLASS_II`, or `CLASS_III`; it must be `NONE` when the species is not regulated and one of the three real classes when it is. Two lifecycle windows live here too: `min_quarantine_days`, the number of days an intake animal of this species must remain in quarantine before it can be cleared (never negative), and `warranty_days`, the livestock warranty coverage window measured in days from a sale's confirmation (never negative).

The remainder of a species entry is its **care-sheet**: `care_temp_low_c` and `care_temp_high_c` bound the enclosure temperature in Celsius, `care_humidity_low_pct` and `care_humidity_high_pct` bound the relative humidity in percent, `feed_interval_days` recommends the number of days between feedings, and `care_feeder_type` names the recommended feeder — one of `CRICKET`, `DUBIA`, `MOUSE_PINKY`, `MOUSE_ADULT`, or `RAT`. A species can be fetched individually or listed (the list may be filtered by `is_regulated`), and a dedicated care-sheet view returns just the husbandry projection — `care_temp_low_c`, `care_temp_high_c`, `care_humidity_low_pct`, `care_humidity_high_pct`, `feed_interval_days`, and `care_feeder_type`. All read operations on species are available to every role; only a `StoreManager` may create one. A create that references husbandry ranges is stored as given.

### 3.2. Animal Intake, Quarantine, and Health

A `StoreManager` takes a new animal into inventory, supplying its `species_id`, a colour/pattern `morph`, an optional `sex` (one of `MALE`, `FEMALE`, or `UNKNOWN`, defaulting to `UNKNOWN`), the `acquisition_cost_cents` the store paid (never negative), the `list_price_cents` sticker price (never negative), and an optional `hatch_date`. At intake the animal's `acquired_by_user_id` is stamped with the acting manager's `X-User-ID` — this is the value later used to enforce warranty segregation of duties. A freshly intaken animal has `health_status` of `HEALTHY` and `status` of `INTAKE`, and its `quarantine_record_id` is empty. An animal's `status` progresses through `INTAKE`, `QUARANTINE`, `AVAILABLE`, `RESERVED`, `SOLD`, and `DECEASED`, with `SOLD` and `DECEASED` terminal; its `health_status` is either `HEALTHY` or `DECEASED`, and `DECEASED` is terminal. Animals may be fetched by id or listed with filters on `species_id` and `status`.

A `VetTech` starts quarantine on an animal that is in `INTAKE`, which creates a **quarantine record** and moves the animal from `INTAKE` to `QUARANTINE`. The new record starts `OPEN`, records its `start_at` as the current logical-clock instant, and computes `required_until` as `start_at` plus the species' `min_quarantine_days` whole days; the animal's `quarantine_record_id` is set to point at it. The record carries an append-only `health_checks` log and a derived `passed_checks_count`, which begins at 0. A `VetTech` appends a health check by supplying a `result` (one of `PASS`, `FAIL`, or `TREAT`) plus an optional `weight_grams` and optional `notes`; the server records the entry with its `check_at` set to the current clock and `vet_user_id` set to the acting technician's `X-User-ID`, then recomputes `passed_checks_count` as the number of entries whose `result` equals `PASS`.

Clearing quarantine is the gate that makes an animal sellable. A `VetTech` may clear an `OPEN` quarantine record only when the logical clock has reached or passed `required_until` (the boundary is inclusive — the exact `required_until` instant qualifies) and `passed_checks_count` is at least 2. If either condition fails, the clear is rejected with `ERR_QUARANTINE_NOT_COMPLETE`. On success the record moves from `OPEN` to `CLEARED`, and that clearance bubbles up to move the animal from `QUARANTINE` to `AVAILABLE` — an animal can only become `AVAILABLE` by way of its quarantine record reaching `CLEARED`. Separately, a `VetTech` may record a death: marking an animal deceased is permitted while it is in `QUARANTINE` or `AVAILABLE`, optionally captures `notes`, sets the animal's `status` to `DECEASED` and `health_status` to `DECEASED`, and — if the animal still has an `OPEN` quarantine record — cascades that record from `OPEN` to `FAILED`. The 0-or-1 quarantine record for an animal, and any individual record, can be read back by every role.

### 3.3. Customers, Permits, and Regulated-Species Compliance

A customer is registered by a `SalesAssociate` or a `StoreManager` with a `full_name`, an `email` that must be unique across all customers, and an optional `loyalty_tier` (one of `STANDARD`, `SILVER`, or `GOLD`, defaulting to `STANDARD`). Each customer also carries a `wallet_credit_cents` balance of store credit, which starts at 0 and grows only from refunds and recall compensation. A customer may be fetched by their owner, a `SalesAssociate`, or a `StoreManager`.

Regulated species may not be sold without a verified permit. A `Customer` (or a `SalesAssociate` acting for them) attaches a **permit** to a customer record by supplying the `customer_id`, a government `permit_number`, the `permit_class` the permit authorizes (one of `CLASS_I`, `CLASS_II`, or `CLASS_III`), an `issued_date`, and an `expiry_date`. A new permit starts in `PENDING_VERIFICATION` with an empty `verified_at` and `verified_by_user_id`. A `StoreManager` verifies a permit that is `PENDING_VERIFICATION` provided the logical clock is still before its `expiry_date` (an already-expired permit cannot be verified, rejected with `ERR_PERMIT_EXPIRED`); verification moves it to `VERIFIED` and stamps `verified_at` with the current clock and `verified_by_user_id` with the manager's `X-User-ID`. A `StoreManager` may later revoke a `VERIFIED` permit, moving it to `REVOKED`. Revocation cascades: every `CONFIRMED` sale of a regulated animal that cites this permit is moved to `VOIDED`, and each such sale's animal is released from `RESERVED` back to `AVAILABLE`. Permits and a customer's permit list are readable by the customer, a `SalesAssociate`, or a `StoreManager`.

### 3.4. The Sale Lifecycle and Pricing

A `SalesAssociate` drafts a **sale** by naming the `animal_id`, the `customer_id`, an optional `permit_id` (required only when the animal's species is regulated), and an optional `sold_at_expo` flag (defaulting to false, and set when the sale is written at an expo booth). Drafting stamps `created_by_user_id` with the associate's `X-User-ID` and computes a **provisional price**, stored in `provisional_price_cents`, while `sale_price_cents`, `confirmed_at`, and `warranty_expires_at` remain empty. A sale's `status` runs through `DRAFT`, `CONFIRMED`, `FULFILLED`, `REFUNDED`, `VOIDED`, and `CLOSED`, with the last three terminal. Sales can be fetched individually and listed with filters on `animal_id`, `customer_id`, `permit_id`, and `status`.

The price of a sale is built up in layers. The base is the animal's `list_price_cents`. A regulated surcharge is then computed as the base multiplied by the surcharge rate for the species' `permit_class` — 0% for `NONE`, 5% for `CLASS_I`, 10% for `CLASS_II`, and 15% for `CLASS_III` — with that product rounded half up to whole cents. A combined discount percentage is then assembled: an expo component of 8% applies whenever `sold_at_expo` is true, and a loyalty component — 0% for `STANDARD`, 5% for `SILVER`, 10% for `GOLD` — applies **only to the final price computed at confirmation**, not to the provisional draft price. The discount amount is the sum of the base and the surcharge, multiplied by that combined discount percentage, rounded half up to whole cents. The gross price is the base plus the surcharge minus the discount. Finally, the price is floored at the animal's `acquisition_cost_cents`: the stored price is the greater of the gross price and the acquisition cost, so the store never sells below what it paid. The provisional variant stored at draft omits the loyalty term entirely (loyalty is only granted once a sale is confirmed and permit-checked); the final variant stored at confirmation includes it.

Confirming a sale is where the compliance and reservation logic converges. A `SalesAssociate` confirms a `DRAFT` sale only when the animal is `AVAILABLE`; if it is not, the confirm is rejected with `ERR_ANIMAL_NOT_AVAILABLE`, and this check is evaluated before the permit checks. For a regulated species, the sale must additionally cite a permit that is present, `VERIFIED`, of a class at least as high as the species' required `permit_class` (with `CLASS_I` lowest and `CLASS_III` highest), and unexpired at the current clock: a missing permit yields `ERR_PERMIT_REQUIRED`, a permit that is not verified or whose class is insufficient yields `ERR_PERMIT_NOT_VERIFIED`, and a permit whose `expiry_date` is at or before the clock yields `ERR_PERMIT_EXPIRED`. On a successful confirm the sale moves from `DRAFT` to `CONFIRMED`, the animal moves from `AVAILABLE` to `RESERVED` (decrementing the store's available-animal count), the final `sale_price_cents` is pinned, `confirmed_at` is set to the current clock, and `warranty_expires_at` is set to `confirmed_at` plus the species' `warranty_days` whole days. From `CONFIRMED`, a `SalesAssociate` may fulfill the sale — moving it to `FULFILLED` and the animal from `RESERVED` to `SOLD` — or void it, moving the sale to `VOIDED` and releasing the animal from `RESERVED` back to `AVAILABLE` (restoring the available-animal count).

### 3.5. Livestock Warranty Claims

Once a sale is `FULFILLED`, its owning `Customer` may submit a **warranty claim** against it, supplying a `claim_type` (either `DOA` for dead-on-arrival or `EARLY_DEATH`) and a free-text `reason`. A new claim starts `SUBMITTED`, with `resolution`, `refund_cents`, `replacement_animal_id`, and `approved_by_user_id` all empty. A claim's `status` runs `SUBMITTED`, `APPROVED`, `DENIED`, and `RESOLVED`, with `DENIED` and `RESOLVED` terminal. Claims can be read by the customer, a `SalesAssociate`, or a `StoreManager`, and listed with filters on `sale_id` and `status`.

A `StoreManager` adjudicates a `SUBMITTED` claim. Approval requires, in order: the claim is `SUBMITTED` and its sale is `FULFILLED`; the approving manager's `X-User-ID` differs from the animal's `acquired_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`); and the logical clock is at or before the sale's `warranty_expires_at` (otherwise `ERR_WARRANTY_EXPIRED`). On approval the claim moves to `APPROVED`, `approved_by_user_id` is stamped, and `refund_cents` is computed: for a `DOA` claim the refund is the full `sale_price_cents` regardless of elapsed time; for an `EARLY_DEATH` claim the refund is prorated by remaining coverage — the remaining days are the whole-day ceiling of the interval from the current clock to `warranty_expires_at`, floored at zero, and the refund is `sale_price_cents` multiplied by those remaining days divided by the species' `warranty_days`, rounded half up to whole cents. Alternatively, a `StoreManager` may deny a `SUBMITTED` claim, optionally supplying a `reason`, which moves it to `DENIED` with no financial effect.

Resolving an approved claim is a branching operation driven by the `resolution` field, chosen at resolve time (one of `REFUND`, `REPLACEMENT`, or `CREDIT`). A `StoreManager` resolves an `APPROVED` claim, moving it to `RESOLVED`, and the three branches carry distinct, parallel side effects. Under `REFUND`, the sale moves from `FULFILLED` to `REFUNDED` and the customer's `wallet_credit_cents` increases by the claim's `refund_cents`. Under `CREDIT`, the customer's `wallet_credit_cents` increases by `refund_cents` and the sale moves from `FULFILLED` to `CLOSED`. Under `REPLACEMENT`, a replacement animal named by `replacement_animal_id` must itself be `AVAILABLE`; that replacement animal is moved from `AVAILABLE` through `RESERVED` to `SOLD`, and the original sale moves from `FULFILLED` to `CLOSED` (no monetary refund is posted on the sale row in this branch).

### 3.6. Feeder Inventory, Subscriptions, and Shipments

A `StoreManager` receives feeder stock as a **feeder batch**, giving its `feeder_type` (one of `CRICKET`, `DUBIA`, `MOUSE_PINKY`, `MOUSE_ADULT`, or `RAT`), its `size` grade (`SMALL`, `MEDIUM`, or `LARGE`), an initial `quantity_on_hand` (never negative), a base `unit_price_cents` before the size multiplier (never negative), a `received_date`, and an `expiry_date`. A batch starts `AVAILABLE`; it becomes `DEPLETED` when allocation drives its `quantity_on_hand` to 0, returns to `AVAILABLE` if a manual reversal restores its quantity above 0, and becomes `RECALLED` when caught by a recall. Batches are readable and listable (filterable by `feeder_type` and `status`) by a `StoreManager` or `SalesAssociate`.

A `Customer` (or a `SalesAssociate` on their behalf) opens a **feeder subscription** with a `customer_id`, a `feeder_type`, a `size`, a `quantity_per_shipment` (at least 1), and a `cadence_days` interval (at least 1). The subscription starts `ACTIVE` with `next_ship_date` set to the current clock and `price_last_shipment_cents` empty; its `status` may be `ACTIVE`, `PAUSED`, `HELD`, or `CANCELLED`, the last being terminal. The owning customer may pause an `ACTIVE` subscription (to `PAUSED`) and resume it later — resuming returns a subscription that is `PAUSED` or `HELD` back to `ACTIVE`. A subscription may be cancelled from any of `ACTIVE`, `PAUSED`, or `HELD`. Subscriptions are readable and listable (filterable by `customer_id` and `status`).

A `SalesAssociate` runs a **shipment** against a subscription. A shipment references its parent `subscription_id`, copies the subscription's `feeder_type` and `size`, and sets `quantity` equal to the subscription's `quantity_per_shipment`, then allocates that quantity from stock by a waterfall recorded in the shipment's `allocations` array. The candidate batches are those that are `AVAILABLE`, match the subscription's feeder type and size, and have an `expiry_date` strictly after the current clock (expired batches are skipped); candidates are ordered by `expiry_date` ascending, ties broken by `created_at` ascending. The waterfall fills the earliest-expiry batch fully before moving to the next, recording each draw as an allocation line holding the `batch_id`, the `quantity` taken from it, and the `unit_cost_cents` charged. The per-unit cost for a line is the batch's `unit_price_cents` multiplied by the size multiplier — 1.00 for `SMALL`, 1.25 for `MEDIUM`, 1.50 for `LARGE` — rounded half up to whole cents; each line's cost is that per-unit price times the line's quantity, and the shipment's `shipment_cost_cents` is the sum of the line costs (each unit price is rounded before multiplying and summing, never summing first). The shipment's `shipment_cost_cents` is also copied to the subscription's `price_last_shipment_cents`. As stock is drawn down, each batch's `quantity_on_hand` is decremented and any batch reaching 0 flips from `AVAILABLE` to `DEPLETED`. Finally the subscription's `next_ship_date` advances by `cadence_days`. For this refusal logic a matching batch (one matching the subscription's feeder type and size) is **eligible** when it is neither `RECALLED` nor expired at the current clock, regardless of its `quantity_on_hand` — so a batch that has merely been depleted to a zero `quantity_on_hand` (status `DEPLETED`) while remaining neither recalled nor expired still counts as eligible stock. If no matching batch is eligible at all — every matching batch has been recalled or has expired — the shipment is refused with `ERR_FEEDER_RECALLED`; if at least one eligible matching batch exists but the total `AVAILABLE` matching quantity (summed over the candidate batches defined above — matching, `AVAILABLE`, unexpired, with a positive `quantity_on_hand`) is less than `quantity_per_shipment`, it is refused with `ERR_INSUFFICIENT_FEEDER_STOCK` — the recalled/expired-exhaustion check takes precedence over the insufficient-quantity check. A shipment starts `SHIPPED` and carries a `reversed_reason` that is empty until it is reversed. A `SalesAssociate` may manually reverse a `SHIPPED` shipment, moving it to `REVERSED` with `reversed_reason` set to `MANUAL`; a manual reversal restores each allocation line's `quantity` to its batch's `quantity_on_hand`, and any batch that was `DEPLETED` returns to `AVAILABLE`. Shipments for a subscription, and individual shipments, are readable by the customer, a `SalesAssociate`, or a `StoreManager`.

### 3.7. Feeder Recalls

When a bad lot of feeders surfaces, a `StoreManager` opens a **recall**, supplying a `reason`, a `target_feeder_type`, and a list of `affected_batch_ids`; each named batch must exist and match the target feeder type. Opening the recall stamps `opened_by_user_id` with the manager's `X-User-ID` and sets the recall `status` to `OPEN`, then cascades broadly. Each affected feeder batch moves from `AVAILABLE` to `RECALLED` and has its `quantity_on_hand` forced to 0. Every `SHIPPED` shipment that allocated any recalled batch is reversed — moved to `REVERSED` with `reversed_reason` set to `RECALL` — but, unlike a manual reversal, a recall does **not** restore the recalled batch quantities. Each subscription behind such a reversed shipment moves from `ACTIVE` to `HELD`, and the subscription's customer is compensated: their `wallet_credit_cents` increases by the reversed shipment's `shipment_cost_cents`. A recall is closed by a `StoreManager` whose `X-User-ID` differs from the recall's `opened_by_user_id` (a four-eyes control; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`); closing moves the recall from `OPEN` to `CLOSED` and stamps `closed_by_user_id`. Recalls are readable and listable (filterable by `status`) by a `StoreManager` or `SalesAssociate`.

### 3.8. Habitat Builds and Special Orders

Custom enclosure work is tracked as a **habitat build**, opened by a `Customer` or a `SalesAssociate` with a `customer_id`, a `spec_summary`, and an initial `quote_cents` (never negative). A new build starts `QUOTED`, with `deposit_cents`, `deposit_paid` (false), `change_orders_total_cents` (0), `installer_id`, `install_start_at`, `install_end_at`, and `final_invoice_cents` all empty or at their defaults. Its `status` progresses through `QUOTED`, `DEPOSIT_PAID`, `IN_PROGRESS`, `CHANGE_REQUESTED`, `DELIVERED`, and `CANCELLED`, the last two terminal. Builds are readable and listable (filterable by `customer_id` and `status`).

The owning `Customer` pays the deposit on a `QUOTED` build, moving it to `DEPOSIT_PAID`: this pins `deposit_cents` as the quote multiplied by 30%, rounded half up to whole cents, and sets `deposit_paid` to true. A `SalesAssociate` then starts the build, moving it from `DEPOSIT_PAID` to `IN_PROGRESS`. While in progress the build can loop through revision rounds: the owning `Customer` files a change order (moving it from `IN_PROGRESS` to `CHANGE_REQUESTED`) by supplying a `delta_cents` amount and the `expected_habitat_build_version` guard described in §2.10; the change order adds its `delta_cents` to the running `change_orders_total_cents` and increments the build's `version` by one. A `SalesAssociate` approves the change to resume work, moving the build from `CHANGE_REQUESTED` back to `IN_PROGRESS`; this cycle may repeat. Independently, a `SalesAssociate` schedules the install by supplying an `installer_id` and an `install_start_at`/`install_end_at` window, which are recorded on the build. Scheduling is subject to a crew buffer: on the same `installer_id`, the gap between the requested window and any other build's install window must be at least 60 minutes, and a request that leaves less than a 60-minute gap is rejected with `ERR_INSTALL_BUFFER_CONFLICT`. A `SalesAssociate` delivers an `IN_PROGRESS` build once its install has been scheduled (its `install_start_at` is set), moving it to `DELIVERED` and pinning `final_invoice_cents` as `quote_cents` plus `change_orders_total_cents` minus the already-paid `deposit_cents`. At any point before delivery — from `QUOTED`, `DEPOSIT_PAID`, `IN_PROGRESS`, or `CHANGE_REQUESTED` — the owning `Customer` may cancel the build, moving it to `CANCELLED`.

### 3.9. Expos and Assignments

The store books weekend events as **expos**, created by a `StoreManager` with a `name`, a `venue`, a `start_at`, an `end_at` (which must be after `start_at`), and a `venue_capacity` — the maximum number of animals that may be concurrently assigned to the expo (never negative). An expo starts `SCHEDULED` and its `status` may become `OPEN`, `CLOSED`, or `CANCELLED`. A `StoreManager` opens a `SCHEDULED` expo (to `OPEN`), closes an `OPEN` expo (to `CLOSED`), or cancels an expo that is `SCHEDULED` or `OPEN` (to `CANCELLED`). Closing an expo ends every one of its still-`ASSIGNED` assignments (moving each to `ENDED`); cancelling an expo instead moves every still-`ASSIGNED` assignment to `CANCELLED`. Expos are readable and listable (filterable by `status`) by a `StoreManager`, `SalesAssociate`, or `Customer`.

A `SalesAssociate` assigns an animal to an expo booth by supplying the `animal_id`. The resulting **expo assignment** references its `expo_id` and `animal_id` and starts `ASSIGNED`, with terminal states `ENDED` and `CANCELLED`. Two guards protect an assignment. First, the same animal may not be assigned to two overlapping expos: if the animal is already `ASSIGNED` to another expo whose window overlaps the target expo's window, the assignment is refused with `ERR_EXPO_OVERLAP`, where windows are compared as half-open intervals — each treated as including its `start_at` and excluding its `end_at`, so two expos that merely touch at an endpoint do not overlap. Second, the target expo may not exceed its `venue_capacity`: if the count of currently `ASSIGNED` assignments on the expo is already at `venue_capacity`, the assignment is refused with `ERR_EXPO_CAPACITY_EXCEEDED`. The overlap check is evaluated before the capacity check, and an animal that is not `AVAILABLE` cannot be assigned in the first place (`ERR_ANIMAL_NOT_AVAILABLE`). Assignments for an expo can be listed, and an individual assignment or the full assignment list (filterable by `animal_id` and `expo_id`) can be read by a `StoreManager`, `SalesAssociate`, or `Customer`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a distinct resource to a collection return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. In the Authorized Role(s) column, "All roles" denotes `StoreManager`, `SalesAssociate`, `VetTech`, and `Customer`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreManager |
| POST | `/species` | Create a species catalogue entry with care-sheet | StoreManager |
| GET | `/species/{id}` | Fetch a species | All roles |
| GET | `/species` | List species | All roles |
| GET | `/species/{id}/care-sheet` | Derived husbandry care-sheet view | All roles |
| POST | `/animals` | Intake a new animal | StoreManager |
| GET | `/animals/{id}` | Fetch an animal | All roles |
| GET | `/animals` | List/filter animals | All roles |
| POST | `/animals/{id}/start-quarantine` | Open a quarantine record; move animal to QUARANTINE | VetTech |
| POST | `/animals/{id}/mark-deceased` | Record an animal death; cascade quarantine failure | VetTech |
| GET | `/animals/{id}/quarantine-record` | Fetch the animal's quarantine record | All roles |
| GET | `/quarantine-records/{id}` | Fetch a quarantine record | All roles |
| POST | `/quarantine-records/{id}/health-checks` | Append a health-check entry | VetTech |
| POST | `/quarantine-records/{id}/clear` | Clear quarantine; bubble animal to AVAILABLE | VetTech |
| POST | `/customers` | Register a customer | SalesAssociate, StoreManager |
| GET | `/customers/{id}` | Fetch a customer | StoreManager, SalesAssociate, Customer |
| POST | `/customers/{id}/permits` | Attach a permit to a customer | Customer, SalesAssociate |
| GET | `/customers/{id}/permits` | List a customer's permits | StoreManager, SalesAssociate, Customer |
| GET | `/permits/{id}` | Fetch a permit | StoreManager, SalesAssociate, Customer |
| POST | `/permits/{id}/verify` | Verify a permit | StoreManager |
| POST | `/permits/{id}/revoke` | Revoke a permit; cascade to confirmed regulated sales | StoreManager |
| POST | `/sales` | Draft a sale | SalesAssociate |
| GET | `/sales/{id}` | Fetch a sale | StoreManager, SalesAssociate, Customer |
| GET | `/sales` | List/filter sales | StoreManager, SalesAssociate, Customer |
| POST | `/sales/{id}/confirm` | Confirm a sale; reserve animal; pin final price | SalesAssociate |
| POST | `/sales/{id}/fulfill` | Fulfill a sale; mark animal SOLD | SalesAssociate |
| POST | `/sales/{id}/void` | Void a confirmed sale; release the animal | SalesAssociate |
| POST | `/sales/{id}/warranty-claims` | Submit a warranty claim against a fulfilled sale | Customer |
| GET | `/warranty-claims/{id}` | Fetch a warranty claim | StoreManager, SalesAssociate, Customer |
| GET | `/warranty-claims` | List/filter warranty claims | StoreManager, SalesAssociate, Customer |
| POST | `/warranty-claims/{id}/approve` | Approve a claim; compute refund | StoreManager |
| POST | `/warranty-claims/{id}/deny` | Deny a claim | StoreManager |
| POST | `/warranty-claims/{id}/resolve` | Resolve an approved claim with a resolution branch | StoreManager |
| POST | `/feeder-batches` | Receive a feeder inventory batch | StoreManager |
| GET | `/feeder-batches/{id}` | Fetch a feeder batch | StoreManager, SalesAssociate |
| GET | `/feeder-batches` | List/filter feeder batches | StoreManager, SalesAssociate |
| POST | `/feeder-subscriptions` | Create a feeder subscription | Customer, SalesAssociate |
| GET | `/feeder-subscriptions/{id}` | Fetch a subscription | StoreManager, SalesAssociate, Customer |
| GET | `/feeder-subscriptions` | List/filter subscriptions | StoreManager, SalesAssociate, Customer |
| POST | `/feeder-subscriptions/{id}/pause` | Pause a subscription | Customer |
| POST | `/feeder-subscriptions/{id}/resume` | Resume a subscription | Customer |
| POST | `/feeder-subscriptions/{id}/cancel` | Cancel a subscription | Customer |
| POST | `/feeder-subscriptions/{id}/shipments` | Ship: waterfall-allocate stock; advance next ship date | SalesAssociate |
| GET | `/feeder-subscriptions/{id}/shipments` | List a subscription's shipments | StoreManager, SalesAssociate, Customer |
| GET | `/shipments/{id}` | Fetch a shipment | StoreManager, SalesAssociate, Customer |
| POST | `/shipments/{id}/reverse` | Manually reverse a shipment; restore batch stock | SalesAssociate |
| POST | `/habitat-builds` | Create a custom habitat build | Customer, SalesAssociate |
| GET | `/habitat-builds/{id}` | Fetch a habitat build | StoreManager, SalesAssociate, Customer |
| GET | `/habitat-builds` | List/filter habitat builds | StoreManager, SalesAssociate, Customer |
| POST | `/habitat-builds/{id}/pay-deposit` | Pay the deposit; pin deposit amount | Customer |
| POST | `/habitat-builds/{id}/start` | Begin the build | SalesAssociate |
| POST | `/habitat-builds/{id}/change-orders` | File a change order (OCC-guarded) | Customer |
| POST | `/habitat-builds/{id}/approve-change` | Approve the change and resume | SalesAssociate |
| POST | `/habitat-builds/{id}/schedule-install` | Schedule the install window (buffer-guarded) | SalesAssociate |
| POST | `/habitat-builds/{id}/deliver` | Deliver the build; pin final invoice | SalesAssociate |
| POST | `/habitat-builds/{id}/cancel` | Cancel a build | Customer |
| POST | `/expos` | Create an expo/event | StoreManager |
| GET | `/expos/{id}` | Fetch an expo | StoreManager, SalesAssociate, Customer |
| GET | `/expos` | List/filter expos | StoreManager, SalesAssociate, Customer |
| POST | `/expos/{id}/open` | Open an expo | StoreManager |
| POST | `/expos/{id}/close` | Close an expo; end assignments | StoreManager |
| POST | `/expos/{id}/cancel` | Cancel an expo; cancel assignments | StoreManager |
| POST | `/expos/{id}/assignments` | Assign an animal to an expo booth | SalesAssociate |
| GET | `/expos/{id}/assignments` | List an expo's assignments | StoreManager, SalesAssociate, Customer |
| GET | `/expo-assignments/{id}` | Fetch an expo assignment | StoreManager, SalesAssociate, Customer |
| GET | `/expo-assignments` | List/filter expo assignments | StoreManager, SalesAssociate, Customer |
| POST | `/recalls` | Open a feeder recall; cascade batch/shipment/subscription | StoreManager |
| GET | `/recalls/{id}` | Fetch a recall | StoreManager, SalesAssociate |
| GET | `/recalls` | List/filter recalls | StoreManager, SalesAssociate |
| POST | `/recalls/{id}/close` | Close a recall (four-eyes) | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_SPECIES_NOT_FOUND` | 404 |
| `ERR_ANIMAL_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_SALE_NOT_FOUND` | 404 |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 |
| `ERR_QUARANTINE_NOT_FOUND` | 404 |
| `ERR_FEEDER_BATCH_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_HABITAT_BUILD_NOT_FOUND` | 404 |
| `ERR_EXPO_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_RECALL_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ANIMAL_NOT_AVAILABLE` | 409 |
| `ERR_QUARANTINE_NOT_COMPLETE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_FEEDER_RECALLED` | 409 |
| `ERR_EXPO_OVERLAP` | 409 |
| `ERR_INSTALL_BUFFER_CONFLICT` | 409 |
| `ERR_EXPO_CAPACITY_EXCEEDED` | 409 |
| `ERR_PERMIT_REQUIRED` | 422 |
| `ERR_PERMIT_NOT_VERIFIED` | 422 |
| `ERR_PERMIT_EXPIRED` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_INSUFFICIENT_FEEDER_STOCK` | 409 |
| `ERR_STALE_VERSION` | 412 |
