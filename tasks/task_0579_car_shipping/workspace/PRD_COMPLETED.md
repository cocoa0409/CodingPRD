# Car Shipping API — Product Requirements Document

## 1. Introduction

The Car Shipping API is the operational backbone of an auto-transport brokerage in the style of a national door-to-door vehicle-shipping marketplace. It coordinates the full journey of a customer's vehicles from an initial price request to a signed, settled, and closed delivery: quoting on open or enclosed trailers across a route, funding a deposit, posting the load to a carrier load board, negotiating dispatch offers in rounds, awarding the load to a vetted carrier, capturing pickup and delivery bill-of-lading inspections, reconciling the cash-on-delivery balance, and adjudicating any damage claims against carrier cargo insurance.

The domain is unforgiving in three ways that this specification is written to control. First, money moves through a ledger rather than through mutable balance fields, so every deposit, cash-on-delivery payment, refund, and insurance payout is an immutable posting that reconciles the order's derived balances. Second, dispatch is gated by a stack of safety and eligibility checks — a suspended carrier, an expired insurance certificate, mismatched trailer equipment, a scheduling collision, or inadequate cargo coverage must all block an award before a vehicle ever leaves the ground. Third, the price a customer is quoted and the price finally settled at delivery may legitimately diverge, because the number of inoperable vehicles observed by the carrier at pickup can differ from what the customer declared when ordering. The sections below define these behaviors precisely so that an implementation, a test suite, and a reader all arrive at exactly the same system.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity in which they act. If either header is missing, the request is rejected with `ERR_MISSING_AUTH`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `Shipper`, `Broker`, `Carrier`, and `Admin`.

Two of these roles are **entity-backed**, meaning the header identity is tied to a persisted record and used for ownership checks:

- When `X-User-Role` is `Shipper`, `X-User-ID` is the `id` of the acting `Shipper`; ownership checks on any resource that references a shipper compare the resource's `shipper_id` to `X-User-ID`. A shipper acting on an order it does not own is rejected with `ERR_NOT_ORDER_OWNER`.
- When `X-User-Role` is `Carrier`, `X-User-ID` is the `id` of the acting `Carrier`; ownership checks compare the resource's `carrier_id` (on offers and assignments) or the assigned carrier of an order to `X-User-ID`. A carrier acting on an offer it does not own is rejected with `ERR_NOT_OFFER_OWNER`; a carrier attempting an inspection on an order it is not the dispatched carrier for is rejected with `ERR_NOT_ASSIGNED_CARRIER`.

The other two roles are **opaque**, meaning the header identity is an operator identifier not tied to any persisted entity:

- When `X-User-Role` is `Broker`, `X-User-ID` is an opaque dispatch-operator identifier. The server may record it in audit context but does not compare it to any entity's `id`.
- When `X-User-Role` is `Admin`, `X-User-ID` is an opaque platform-superuser identifier. The server does not compare it to any entity's `id`; Admin may read every resource and performs claim adjudication, carrier suspension, ledger voids, and clock control.

Validation of a request proceeds in a fixed priority order, and the first failing check determines the error returned: authentication (`ERR_MISSING_AUTH`, 401) is checked first, then role authorization (`ERR_FORBIDDEN_ROLE`, 403), then existence of every path resource (`ERR_NOT_FOUND`, 404), then resource ownership for entity-backed actors (`ERR_NOT_ORDER_OWNER` / `ERR_NOT_OFFER_OWNER` / `ERR_NOT_ASSIGNED_CARRIER`, 403), then whether the target resource is in a state that permits the transition (`ERR_INVALID_STATE`, 409, unless a more specific domain state error is declared for that transition), then request-body shape (`ERR_INVALID_REQUEST`, 422), and finally the domain-specific temporal, fiscal, and safety checks described throughout §2 and §3.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Nearly every persisted resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID, unique across all resources, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 on creation and increments by 1 on every mutation. It is the basis of optimistic concurrency control (see §2.7).

There is one deliberate exception: a `LedgerEntry` is an immutable financial posting and carries only `id` and `created_at`. It has no `updated_at` and no `version`; once posted, its content never changes (a ledger entry is retired by voiding it, which is itself modeled as a status flip rather than an in-place mutation of the original amounts). All other entities — `Carrier`, `ShipmentOrder`, `Vehicle`, `Quote`, `LoadListing`, `DispatchOffer`, `Assignment`, `Inspection`, `Claim`, `Shipper`, and `Terminal` — carry the full `id` / `created_at` / `updated_at` / `version` set.

Whenever a derived field on a resource changes as a side effect of another operation, that counts as a mutation of the resource: its `updated_at` is refreshed and its `version` increments. In particular, every workflow transition on a `ShipmentOrder` increments the order's `version` by 1.

### 2.5. Monetary Values and Precision

All monetary amounts in the system are stored and transmitted as **integer cents** (fields ending in `_cents`). No amount is ever a fractional cent. Wherever a calculation produces a non-integer intermediate (a percentage surcharge, a percentage discount, a percentage deposit), the result is rounded to a whole number of cents using the **round-half-up** convention.

One precision rule is load-bearing for the distance base: when mileage is priced across bands, each band's contribution is summed first and only the final sum is rounded to whole cents — the individual bands are never rounded before summing. This "sum-then-round" rule is called out again where the quote formula is defined.

### 2.6. The Logical Clock and Time-Sensitive Validations

The server keeps a **logical clock** that is the sole source of "now" for every time-sensitive check. At startup the logical clock reads `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time. An `Admin` may advance or set the clock to a supplied instant; the request carries a `to_iso8601` field naming the new current time. This capability governs two expiry checks:

- **Quote expiry.** A quote's `valid_until` is compared against the logical clock at acceptance time; a quote may only be accepted while the clock is at or before `valid_until`.
- **Insurance-certificate expiry.** A carrier's `insurance_expiry_date` is compared against the logical clock at dispatch time; a carrier may only be dispatched while the clock is at or before its `insurance_expiry_date`.

### 2.7. Optimistic Concurrency Control

Generating a quote is guarded by optimistic concurrency control, because a quote prices whatever vehicles are attached to the order at the moment it runs, and attaching a vehicle advances the order's `version`. The quote-generation request must carry an `expected_order_version` field holding the client's last observed `ShipmentOrder.version`. If `expected_order_version` does not equal the order's current `version` — for example because another writer attached a vehicle after the client last read the order — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no quote is created. This prevents a client from receiving a quote priced against a vehicle set it never saw. No other endpoint takes a version field; only quote generation is version-guarded.

### 2.8. State Propagation and Cascading Consistency

Many operations mutate more than one entity. When an operation on one resource changes the eligibility or standing of a related resource, the system performs the cascade immediately and in full — there is no eventual reconciliation and no partial application. For example, awarding a load both advances the order and declines every competing offer on the listing; revoking a dispatch both reopens the order and reopens the listing; delivering completes the assignment. Each such cascade that touches a resource is a mutation of that resource, refreshing its `updated_at` and incrementing its `version`. The specific cascades are described inline with the workflows they belong to in §3; the governing rule here is that they are atomic with the triggering operation and always leave derived fields consistent with the entities they summarize.

### 2.9. Nested Path Resolution

Several endpoints address a resource nested under a parent, such as a quote under an order or an offer under a listing. For any such path, the system validates each identifier left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A quote acceptance under a non-existent order fails on the order before the quote is ever examined; an offer action under a non-existent listing fails on the listing first. This ordering holds for creation and action endpoints as well as reads.

### 2.10. Ledger Integrity and Balance Reconciliation

An order's cash position is never stored as a directly writable number; it is **reconciled from the ledger** every time a `LedgerEntry` is posted or voided. Each ledger entry has a `kind` — one of `DEPOSIT`, `COD_PAYMENT`, `REFUND`, or `CLAIM_PAYOUT` — and a signed `amount_cents`, where deposits and cash-on-delivery payments are recorded as positive inflows and refunds and claim payouts as negative outflows. Only entries whose `status` is `POSTED` participate in reconciliation; a `VOIDED` entry is excluded.

Reconciliation recomputes two derived fields on the order. `amount_paid_cents` is the sum of `amount_cents` over all `POSTED` ledger entries whose `kind` is `DEPOSIT` or `COD_PAYMENT` — inflows only. `outstanding_balance_cents` is the order's `quoted_total_cents` minus `amount_paid_cents`. Crucially, `REFUND` and `CLAIM_PAYOUT` entries are broker-to-shipper cash going out; they do **not** reduce `outstanding_balance_cents`. Only `DEPOSIT` and `COD_PAYMENT` inflows reduce what the shipper still owes.

### 2.11. Carrier Insurance Exposure Accounting

A carrier's insured exposure is read in two distinct ways, and the two readings deliberately differ for a carrier hauling more than one active load. The **per-load** reading is the sum of `declared_value_cents` across the vehicles of the single order being dispatched; it is the value enforced by the insurance-adequacy gate at dispatch. The **aggregate** reading is the sum of `declared_value_cents` across the vehicles of every order currently assigned to that carrier whose `Assignment` status is `DISPATCHED` or `PICKED_UP`, including the order just dispatched. The aggregate reading is stored on the carrier's `aggregate_exposure_cents` field as a read-only monitoring figure; it is informational and is never used to gate an operation. It is recomputed whenever an assignment of the carrier changes status — on award, on revoke, and on delivery completion. For a carrier holding two active loads, `aggregate_exposure_cents` counts both while the per-load gate sees only one.

## 3. Business Logic & Workflows

### 3.1. Onboarding Participants: Shippers, Carriers, and Terminals

A customer joins the platform as a `Shipper`, registered with a contact `email` and a `full_name`. The `email` must be unique across shippers; a duplicate registration is rejected with `ERR_DUPLICATE_EMAIL`. A shipper may register itself, and an `Admin` may register one on a customer's behalf.

Carriers are onboarded onto the load board by a `Broker` (or an `Admin`). A `Carrier` is created with a `legal_name`, its federal motor-carrier authority number `mc_number`, a per-load cargo insurance ceiling `cargo_insurance_limit_cents`, the certificate expiry date `insurance_expiry_date`, and the trailer `equipment_type` it operates, which is either `OPEN` or `ENCLOSED`. An optional broker `rating` between 0.0 and 5.0 may be supplied; when omitted it defaults to 3.0 and serves as the dispatch ranking key. The `mc_number` must be unique across carriers; a duplicate is rejected with `ERR_DUPLICATE_MC_NUMBER`. A newly registered carrier begins in `ACTIVE` status with its `version` at 1 and its `aggregate_exposure_cents` at 0. An `Admin` may later suspend a carrier, flipping its `status` from `ACTIVE` to `SUSPENDED`; a suspended carrier can no longer be awarded a load. Suspending a carrier that is already `SUSPENDED` is an idempotent no-op that returns the carrier unchanged (its `version` is not incremented).

Terminal facilities support terminal-to-terminal delivery. A `Broker` or `Admin` registers a `Terminal` with a facility `name`, a `dock_zip` (recorded as a non-empty string; its five-digit shape is not separately validated), a concurrent `dock_count` that must be at least 1, and an optional `buffer_minutes` turnaround pad that defaults to 60. The `buffer_minutes` value is applied symmetrically to each side of a reserved dock slot when the system checks for slot overlaps.

### 3.2. Building the Order: Draft Creation and Vehicles

A `Shipper` opens a shipment by creating an order, which is born in `DRAFT` status with its `shipper_id` set from `X-User-ID` and its `version` at 1. The order captures the pickup `origin_zip` and delivery `dest_zip` (both recorded as non-empty strings; their five-digit ZIP shape is not separately validated), the quoted route distance `route_miles` (which must be greater than 0), and the `transport_type`, either `OPEN` or `ENCLOSED`. Two enum options carry defaults: `delivery_mode` is `DOOR_TO_DOOR` or `TERMINAL` and defaults to `DOOR_TO_DOOR`, and `service_level` is `STANDARD` or `EXPEDITED` and defaults to `STANDARD`. The requested pickup window is given by `pickup_window_start` and `pickup_window_end`, and the window close must be strictly later than the window open. A malformed body — a non-positive `route_miles`, a window whose end is at or before its start, an invalid enum member — is rejected with `ERR_INVALID_REQUEST`.

When `delivery_mode` is `TERMINAL`, three additional fields become mandatory: the `terminal_id` of the reserved facility, and the reserved dock window `terminal_slot_start` and `terminal_slot_end`, where the slot close must be strictly later than the slot open. If any of the three is absent for a terminal-mode order, or the slot window is inverted, the request is rejected with `ERR_INVALID_REQUEST`. For door-to-door orders these three fields remain null.

Terminal-mode creation additionally runs a **dock-overlap** check against the chosen terminal. Consider every other order already reserved at that terminal whose status is not `CANCELLED`. Each such order's reserved slot is expanded by the terminal's `buffer_minutes` on both sides, forming a buffered interval running from its `terminal_slot_start` minus the buffer to its `terminal_slot_end` plus the buffer. Treat this buffered interval as closed, so that merely touching endpoints count as intersecting. Count the other orders whose buffered interval intersects the new order's requested `[terminal_slot_start, terminal_slot_end]`. If that count reaches the terminal's `dock_count` — that is, if admitting this reservation would leave no free dock — the creation is rejected with `ERR_TERMINAL_SLOT_CONFLICT`; the reservation is admitted only while the number of conflicting orders remains below `dock_count`.

Within a `DRAFT` order the shipper attaches one or more vehicles. A `Vehicle` belongs to its order via `order_id` and records the `make`, `model`, and `year`, an `is_inoperable` flag that defaults to false and marks a non-running unit that draws a surcharge, and the owner-`declared_value_cents` used later for the insurance-adequacy check. Because attaching a vehicle changes the order's pricing basis, each attachment increments the order's `version` by 1 — which is precisely why quoting is version-guarded (§2.7).

### 3.3. Pricing the Load: Quote Generation and Acceptance

Either the `Shipper` or a `Broker` may generate a quote for an order, and the request must carry `expected_order_version` matching the order's current `version`, failing which it is rejected with `ERR_STALE_VERSION` as described in §2.7. Generation runs the pricing algorithm over all vehicles currently attached to the order and produces a `Quote` in `OFFERED` status. Its `valid_until` is set to its `created_at` plus 72 hours, after which it can no longer be accepted. Generating a fresh quote supersedes any earlier live quote on the order: every other `OFFERED` quote on that order transitions to `SUPERSEDED`. Each generation also increments the order's `version` by 1.

The quote total is assembled in a fixed order, each step reading only the results of prior steps:

1. **Distance base (`base_cents`).** The route is priced across three marginal mileage bands. The first 500 miles — miles 1 through 500 — are billed at 95 cents per mile. Miles 501 through 1500 are billed at 75 cents per mile. Every mile beyond 1500 is billed at 60 cents per mile. Each band contributes the number of the order's miles falling within it multiplied by that band's per-mile rate; the three contributions are summed and only that final sum is rounded to whole cents. The bands are never rounded individually. For instance, a 2000-mile route contributes 500 miles at 95 cents, 1000 miles at 75 cents, and 500 miles at 60 cents.

2. **Transport surcharge (`transport_surcharge_cents`).** If `transport_type` is `ENCLOSED`, an enclosed surcharge of 40% of `base_cents`, rounded half-up, is added; otherwise the enclosed surcharge is zero. If `service_level` is `EXPEDITED`, an expedited surcharge of 25% of `base_cents`, rounded half-up, is added; otherwise the expedited surcharge is zero. `transport_surcharge_cents` is the sum of the enclosed and expedited surcharges.

3. **Inoperable surcharge (`inoperable_surcharge_cents`).** Each vehicle whose `is_inoperable` flag is true adds a flat 15000 cents ($150). The surcharge is 15000 multiplied by the count of inoperable vehicles on the order.

4. **Multi-car discount (`multi_car_discount_cents`).** When the order carries two or more vehicles, a volume discount applies to the sum of `base_cents` and `transport_surcharge_cents`. Let the vehicle count be the number of vehicles on the order. The raw discount is 5% of that sum for each vehicle beyond the first — that is, 5% multiplied by (the vehicle count minus 1), applied to (`base_cents` plus `transport_surcharge_cents`), rounded half-up. The discount is then capped so it never exceeds 15% of (`base_cents` plus `transport_surcharge_cents`). With fewer than two vehicles the discount is zero.

5. **Total (`total_cents`).** The quote total is `base_cents` plus `transport_surcharge_cents` plus `inoperable_surcharge_cents` minus `multi_car_discount_cents`.

When the `Shipper` accepts an `OFFERED` quote, the order advances from `DRAFT` to `QUOTED`; the order's own current status is not itself checked as a precondition, so acceptance succeeds from whatever state the order is in and sets its `status` to `QUOTED`. Acceptance requires that the order have at least one vehicle, else it is rejected with `ERR_NO_VEHICLES`; that the quote be in `OFFERED` status, else `ERR_QUOTE_NOT_OFFERED`; and that the logical clock be at or before the quote's `valid_until`, else `ERR_QUOTE_EXPIRED`. On acceptance the order's `quoted_total_cents` is locked to the quote's `total_cents`, the accepted quote flips to `ACCEPTED` while all sibling `OFFERED` quotes on the order flip to `SUPERSEDED`, and the deposit split runs.

The **deposit split** partitions `quoted_total_cents` into the broker's cut and the carrier's cash-on-delivery balance. The raw deposit is 20% of `quoted_total_cents`, rounded half-up. `deposit_cents` is that raw figure clamped to a floor of 10000 cents ($100) and a ceiling of 40000 cents ($400): if the raw figure is below the floor it becomes 10000, if above the ceiling it becomes 40000, otherwise it stands. `cod_balance_cents` is `quoted_total_cents` minus `deposit_cents`, so that `deposit_cents` and `cod_balance_cents` always sum exactly to `quoted_total_cents`. At this point `amount_paid_cents` is still 0, so `outstanding_balance_cents` equals `quoted_total_cents`. Acceptance increments the order's `version` by 1.

### 3.4. Funding and Posting to the Load Board

Payments, refunds, and payouts are recorded as ledger entries by a `Broker` or `Admin` against an order. A `LedgerEntry` carries a `kind` and a signed `amount_cents` and is posted in `POSTED` status, after which the order's balances are reconciled per §2.10. The supplied `amount_cents` must carry the sign matching its `kind`: a `DEPOSIT` or `COD_PAYMENT` must be a strictly positive integer and a `REFUND` or `CLAIM_PAYOUT` a strictly negative integer, else the posting is rejected with `ERR_INVALID_REQUEST`. A `DEPOSIT` posting funds the broker's cut; a `COD_PAYMENT` records the carrier's cash-on-delivery collection. A `COD_PAYMENT` must not overpay: its `amount_cents` may not exceed the order's current `outstanding_balance_cents`, and an attempt to do so is rejected with `ERR_OVERPAYMENT`. An `Admin` may void a `POSTED` entry, flipping its `status` to `VOIDED` and triggering a fresh reconciliation that excludes it; voiding an entry that is already `VOIDED` is an idempotent no-op that returns it unchanged with no further reconciliation.

Once an order is `QUOTED` and its deposit has been funded, a `Broker` posts it to the load board, advancing the order from `QUOTED` to `LISTED` and creating a `LoadListing` in `OPEN` status. Listing carries a single input, the advertised carrier pay `offered_carrier_pay_cents`. Two preconditions guard the transition. First, the deposit must already be paid: the order's `amount_paid_cents` must be at least its `deposit_cents`, established by a `POSTED` `DEPOSIT` entry, and otherwise the request is rejected with `ERR_DEPOSIT_NOT_PAID`. Second, `offered_carrier_pay_cents` may not exceed the order's `quoted_total_cents`, else `ERR_PAY_EXCEEDS_TOTAL`. On creation the listing's `expedited` field mirrors whether the order's `service_level` is `EXPEDITED`, its `best_offer_id` is null until offers arrive, and the order's `version` increments by 1.

### 3.5. Dispatch Negotiation: Offers, Counters, and the Award

A `Carrier` bids on an `OPEN` listing by submitting an offer, which is created in `PENDING` status with its `carrier_id` taken from `X-User-ID` and its `round_no` at 1. The offer names the carrier's asking pay `ask_pay_cents` and a promised `pickup_eta`. The promised pickup time must fall within the order's requested window as a closed interval — at or after `pickup_window_start` and at or before `pickup_window_end`, with both endpoints inclusive — and an eta outside that window is rejected with `ERR_PICKUP_ETA_OUT_OF_WINDOW`. Each time an offer is created or re-asked, the listing's `best_offer_id` is recomputed to point at the current lowest-ask `PENDING` offer on the listing, breaking ties by earliest `created_at`; it is null when no `PENDING` offer remains.

Negotiation runs in rounds. A `Broker` may counter a `PENDING` offer, which advances it from `PENDING` to `COUNTERED` and increments its `round_no` by 1; the counter request carries the broker's target `counter_pay_cents`. Countering requires the offer to be `PENDING`, else `ERR_OFFER_NOT_ACTIVE`, and the listing to still be `OPEN`, else `ERR_LISTING_NOT_OPEN`. The owning `Carrier` may then re-ask, moving the offer from `COUNTERED` back to `PENDING`, updating `ask_pay_cents` to the new ask (and optionally a new `pickup_eta`), incrementing `round_no` by 1, and recomputing the listing's `best_offer_id`. A `pickup_eta` supplied on re-ask is validated only for well-formed datetime shape and is not re-checked against the order's pickup window. Re-asking requires the offer to be `COUNTERED`, else `ERR_OFFER_NOT_ACTIVE`, and the acting carrier to be the offer's owner, else `ERR_NOT_OFFER_OWNER`. This `PENDING` ↔ `COUNTERED` loop may repeat. A `Carrier` may also withdraw its own offer from either `PENDING` or `COUNTERED`, moving it to `WITHDRAWN` and recomputing `best_offer_id`; withdrawal requires an active offer (`ERR_OFFER_NOT_ACTIVE`) owned by the caller (`ERR_NOT_OFFER_OWNER`).

The award is the pivotal transition. When a `Broker` accepts an offer, the order advances from `LISTED` to `DISPATCHED` and a stack of eligibility gates is evaluated in the following order, the first failure determining the rejection:

1. The offer must be in `PENDING` or `COUNTERED` status, else `ERR_OFFER_NOT_ACTIVE`.
2. The carrier must not be `SUSPENDED`, else `ERR_CARRIER_SUSPENDED`.
3. The carrier's insurance certificate must be current — the logical clock at or before `insurance_expiry_date` — else `ERR_INSURANCE_EXPIRED`.
4. The carrier must have no scheduling collision. No other `Assignment` of this carrier in `DISPATCHED` or `PICKED_UP` status may have an order pickup window that overlaps this order's window, evaluated as a **half-open** interval `[pickup_window_start, pickup_window_end)` — windows that merely touch at an endpoint do not conflict. A collision is rejected with `ERR_CARRIER_SCHEDULE_CONFLICT`.
5. The carrier's `equipment_type` must equal the order's `transport_type`, else `ERR_EQUIPMENT_MISMATCH`.
6. The carrier's cargo coverage must be adequate for this load: `cargo_insurance_limit_cents` must be at least the per-load exposure, the sum of `declared_value_cents` across the order's vehicles. Otherwise the award is rejected with `ERR_INSURANCE_INADEQUATE`.
7. The accepted offer's `ask_pay_cents` may not exceed the order's `quoted_total_cents`, else `ERR_PAY_EXCEEDS_TOTAL`.

On a clean award the system creates an `Assignment` in `DISPATCHED` status whose `carrier_pay_cents` is locked to the accepted offer's `ask_pay_cents`, and which records the `order_id`, the winning `carrier_id`, and the accepted `offer_id`. The order's `assigned_carrier_id` is set to the carrier, the accepted offer flips to `ACCEPTED`, the listing flips from `OPEN` to `AWARDED`, and every sibling offer on that listing still in `PENDING` or `COUNTERED` flips to `DECLINED`. The carrier's `aggregate_exposure_cents` is recomputed to include this newly active load, and the order's `version` increments by 1.

### 3.6. Revoking a Dispatch Before Pickup

A `Broker` may revoke a dispatch that has not yet begun. Revocation requires the `Assignment` to be in `DISPATCHED` status, else `ERR_ASSIGNMENT_NOT_DISPATCHED`, and requires that no `PICKUP` inspection exists yet for the order, else `ERR_ALREADY_PICKED_UP` — once a vehicle is on the truck, the load can no longer be pulled back. On revoke the order moves from `DISPATCHED` back to `LISTED`, the assignment flips to `REVOKED`, the order's `assigned_carrier_id` is cleared to null, and the `LoadListing` reopens from `AWARDED` to `OPEN` with its `best_offer_id` recomputed so the board can be reworked. Because the load leaves the carrier's active set, the carrier's `aggregate_exposure_cents` is recomputed, and the order's `version` increments by 1.

### 3.7. On the Road: Pickup and Delivery Inspections

Bill-of-lading inspections are recorded by the dispatched `Carrier` and drive the order to its terminal delivery state. An `Inspection` names its `phase` — `PICKUP` or `DELIVERY` — and records a `damage_count` of new damage points noted on that leg (default 0), an `observed_inoperable_count` of vehicles found non-running at that leg (default 0), and the `odometer` reading. The carrier that files it is stamped into `signed_by_carrier_id`. Only the order's assigned carrier may inspect: the acting carrier must equal the order's dispatched carrier, else `ERR_NOT_ASSIGNED_CARRIER`. On this endpoint request-body validation (`ERR_INVALID_REQUEST`) is applied after the assigned-carrier ownership check but before the duplicate-inspection and order-state checks, so a malformed body is reported ahead of any state conflict.

The `PICKUP` inspection advances the order from `DISPATCHED` to `PICKED_UP`. It requires that the assignment be `DISPATCHED` and belong to the acting carrier (`ERR_NOT_ASSIGNED_CARRIER`), and that no prior `PICKUP` inspection already exist for the order, else `ERR_DUPLICATE_INSPECTION`. The `observed_inoperable_count` captured here is the figure that later re-prices the load at settlement.

The `DELIVERY` inspection advances the order from `PICKED_UP` to `DELIVERED`. It requires that a `PICKUP` inspection already exist and that no prior `DELIVERY` inspection exist, else `ERR_DUPLICATE_INSPECTION`. Delivery does three further things: it completes the load's `Assignment`, flipping it from `DISPATCHED` to `COMPLETED`; it recomputes the carrier's `aggregate_exposure_cents` because the load leaves the active set; and it runs **settlement pricing** to fill `settled_total_cents`.

Settlement re-runs the quote formula with exactly one substitution: the inoperable count comes from what the carrier *observed* at pickup rather than what the shipper *declared* at order creation. The `base_cents`, `transport_surcharge_cents`, and `multi_car_discount_cents` are unchanged from the accepted quote, since route, transport type, and service level did not change. The settlement inoperable surcharge is 15000 cents multiplied by the `PICKUP` inspection's `observed_inoperable_count`, and `settled_total_cents` is `base_cents` plus `transport_surcharge_cents` plus that observed inoperable surcharge minus `multi_car_discount_cents`. The settled figure is informational: it records what the load would have priced at given the observed condition and diverges from `quoted_total_cents` exactly when the observed inoperable count differs from the declared count used at quote time. It does **not** alter `outstanding_balance_cents`. Every inspection increments the order's `version` by 1.

### 3.8. Settlement and Closing the Order

As the carrier collects the balance on delivery, a `Broker` or `Admin` posts `COD_PAYMENT` entries against the order (subject to the overpayment guard of §3.4), driving `amount_paid_cents` up and `outstanding_balance_cents` down toward zero. A `Broker` closes a `DELIVERED` order, advancing it from `DELIVERED` to the terminal `CLOSED` state. Closing has two preconditions: the order's `outstanding_balance_cents` must be exactly 0, else `ERR_BALANCE_OUTSTANDING`; and the order must have no open claim, that is `has_open_claim` must be false, else `ERR_OPEN_CLAIM`. Closing increments the order's `version` by 1.

An order may instead be cancelled by its `Shipper` while it is still early in its life — only from `DRAFT`, `QUOTED`, or `LISTED`. A cancel attempt from any later state (`DISPATCHED` onward) is rejected with `ERR_INVALID_STATE`. Cancellation moves the order to the terminal `CANCELLED` state. If a `POSTED` `DEPOSIT` exists on the order, the system posts a compensating `REFUND` ledger entry equal to the negative of `deposit_cents` and reconciles `amount_paid_cents` and `outstanding_balance_cents` accordingly (the refund itself, being an outflow, does not raise the outstanding balance). Any `OPEN` `LoadListing` on the order is withdrawn to `WITHDRAWN`, and its offers still in `PENDING` or `COUNTERED` flip to `DECLINED`. Cancellation increments the order's `version` by 1.

### 3.9. Damage Claims and Insurance Adjudication

If a delivered vehicle arrives damaged, the `Shipper` files a `Claim` against the order, stating the amount sought in the positive-integer `claimed_cents`. Filing itself carries no order-status precondition — a claim may be filed while the order is in any state — and the requirement that the order be `DELIVERED` with recorded damage is enforced only at approval. The claim opens in `SUBMITTED` status, snapshots the responsible carrier into its `carrier_id` from the order's `assigned_carrier_id`, and sets the order's `has_open_claim` to true. A claim remains "open" while it sits in any non-terminal status, which is what blocks the order from closing.

Claim review is a cycle managed largely by an `Admin`. From `SUBMITTED`, an admin may **return** the claim for more information, moving it to `RETURNED_FOR_INFO`; this requires the claim to be `SUBMITTED`, else `ERR_CLAIM_NOT_ACTIONABLE`. The owning `Shipper` may then **resubmit**, moving it from `RETURNED_FOR_INFO` back to `SUBMITTED` and updating `claimed_cents` to the resubmitted amount; resubmission requires the claim to be `RETURNED_FOR_INFO` (`ERR_CLAIM_NOT_ACTIONABLE`) and the acting shipper to be the order's owner (`ERR_NOT_ORDER_OWNER`). This `SUBMITTED` ↔ `RETURNED_FOR_INFO` review loop may repeat.

An `Admin` **approves** a `SUBMITTED` claim, which requires the claim to be `SUBMITTED` (`ERR_CLAIM_NOT_ACTIONABLE`) and requires damage on record: the order must be `DELIVERED` and a `DELIVERY` inspection with a `damage_count` greater than 0 must exist, else `ERR_NO_DAMAGE_ON_RECORD`. Approval runs the **adjudication** calculation to set `approved_cents` and moves the claim to `APPROVED`. The payout is bounded twice: the eligible amount is the smaller of `claimed_cents` and the sum of `declared_value_cents` across the order's vehicles, and `approved_cents` is the smaller of that eligible amount and the responsible carrier's `cargo_insurance_limit_cents`. If this yields zero — for instance when the carrier's limit is zero — approval still succeeds with `approved_cents` of 0, a documented denial-equivalent payout.

Alternatively an `Admin` may **deny** a claim from either `SUBMITTED` or `RETURNED_FOR_INFO` (`ERR_CLAIM_NOT_ACTIONABLE` otherwise), moving it to the terminal `DENIED` state and recomputing the order's `has_open_claim`. Finally, an `Admin` **pays** an `APPROVED` claim (`ERR_CLAIM_NOT_ACTIONABLE` otherwise), which posts a `CLAIM_PAYOUT` ledger entry equal to the negative of `approved_cents` on the order, reconciles `amount_paid_cents` and `outstanding_balance_cents`, moves the claim to the terminal `PAID` state, and recomputes the order's `has_open_claim`. Because a claim payout is an outflow, it does not reduce `outstanding_balance_cents`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. All list endpoints accept the pagination query parameters `limit` and `offset` and the filter parameters noted in their descriptions.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shippers` | Register a shipper account | Shipper, Admin |
| GET | `/shippers/{shipperId}` | Get a shipper | Shipper, Admin |
| POST | `/terminals` | Register a terminal facility | Broker, Admin |
| GET | `/terminals` | List terminals (filter `dock_zip`) | Shipper, Broker, Admin |
| GET | `/terminals/{terminalId}` | Get a terminal | Shipper, Broker, Admin |
| POST | `/carriers` | Register a carrier | Broker, Admin |
| GET | `/carriers` | List carriers (filter `equipment_type`, `status`) | Broker, Admin |
| GET | `/carriers/{carrierId}` | Get a carrier | Broker, Admin, Carrier |
| POST | `/carriers/{carrierId}/suspend` | Suspend a carrier | Admin |
| POST | `/shipment-orders` | Create a shipment order in DRAFT | Shipper |
| GET | `/shipment-orders` | List orders (filter `shipper_id`, `status`, `assigned_carrier_id`, `terminal_id`) | Shipper, Broker, Admin |
| GET | `/shipment-orders/{orderId}` | Get a shipment order | Shipper, Broker, Admin, Carrier |
| POST | `/shipment-orders/{orderId}/cancel` | Cancel an order; refund deposit if paid | Shipper |
| POST | `/shipment-orders/{orderId}/close` | Close a delivered, fully paid order | Broker |
| POST | `/shipment-orders/{orderId}/vehicles` | Attach a vehicle to a DRAFT order | Shipper |
| GET | `/vehicles` | List vehicles (filter `order_id`) | Shipper, Broker, Admin, Carrier |
| GET | `/vehicles/{vehicleId}` | Get a vehicle | Shipper, Broker, Admin, Carrier |
| POST | `/shipment-orders/{orderId}/quotes` | Generate a priced quote (OCC guarded) | Shipper, Broker |
| GET | `/quotes` | List quotes (filter `order_id`, `status`) | Shipper, Broker, Admin |
| GET | `/quotes/{quoteId}` | Get a quote | Shipper, Broker, Admin |
| POST | `/shipment-orders/{orderId}/quotes/{quoteId}/accept` | Accept a quote, locking price and deposit split | Shipper |
| POST | `/shipment-orders/{orderId}/ledger-entries` | Post a payment/refund/payout entry | Broker, Admin |
| GET | `/ledger-entries` | List ledger entries (filter `order_id`, `kind`, `status`) | Broker, Admin, Shipper |
| GET | `/ledger-entries/{ledgerEntryId}` | Get a ledger entry | Broker, Admin, Shipper |
| POST | `/ledger-entries/{ledgerEntryId}/void` | Void a posted ledger entry | Admin |
| POST | `/shipment-orders/{orderId}/listings` | Post a quoted order to the load board | Broker |
| GET | `/listings` | List listings (filter `order_id`, `status`, `expedited`) | Broker, Admin, Carrier |
| GET | `/listings/{listingId}` | Get a listing | Broker, Admin, Carrier |
| POST | `/listings/{listingId}/offers` | Carrier bids on an open listing | Carrier |
| GET | `/offers` | List offers (filter `listing_id`, `carrier_id`, `status`) | Broker, Admin, Carrier |
| GET | `/offers/{offerId}` | Get a dispatch offer | Broker, Admin, Carrier |
| POST | `/listings/{listingId}/offers/{offerId}/counter` | Broker counters a pending offer | Broker |
| POST | `/listings/{listingId}/offers/{offerId}/reoffer` | Carrier re-asks after a counter | Carrier |
| POST | `/listings/{listingId}/offers/{offerId}/withdraw` | Carrier withdraws its offer | Carrier |
| POST | `/listings/{listingId}/offers/{offerId}/accept` | Broker accepts an offer, dispatching the carrier | Broker |
| GET | `/assignments` | List assignments (filter `order_id`, `carrier_id`, `offer_id`, `status`) | Broker, Admin, Carrier |
| GET | `/assignments/{assignmentId}` | Get an assignment | Broker, Admin, Carrier |
| POST | `/assignments/{assignmentId}/revoke` | Revoke a dispatch before pickup | Broker |
| POST | `/shipment-orders/{orderId}/inspections` | Record a BOL inspection (PICKUP or DELIVERY) | Carrier |
| GET | `/inspections` | List inspections (filter `order_id`, `signed_by_carrier_id`, `phase`) | Shipper, Broker, Admin, Carrier |
| GET | `/inspections/{inspectionId}` | Get an inspection | Shipper, Broker, Admin, Carrier |
| POST | `/shipment-orders/{orderId}/claims` | File a damage claim | Shipper |
| GET | `/claims` | List claims (filter `order_id`, `carrier_id`, `status`) | Shipper, Broker, Admin, Carrier |
| GET | `/claims/{claimId}` | Get a claim | Shipper, Broker, Admin, Carrier |
| POST | `/claims/{claimId}/return` | Return a claim for more info | Admin |
| POST | `/claims/{claimId}/resubmit` | Resubmit a returned claim | Shipper |
| POST | `/claims/{claimId}/approve` | Approve a claim, computing the capped payout | Admin |
| POST | `/claims/{claimId}/deny` | Deny a claim | Admin |
| POST | `/claims/{claimId}/pay` | Pay an approved claim | Admin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_ORDER_OWNER` | 403 |
| `ERR_NOT_OFFER_OWNER` | 403 |
| `ERR_NOT_ASSIGNED_CARRIER` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_VEHICLES` | 409 |
| `ERR_QUOTE_NOT_OFFERED` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_DEPOSIT_NOT_PAID` | 402 |
| `ERR_PAY_EXCEEDS_TOTAL` | 402 |
| `ERR_OVERPAYMENT` | 402 |
| `ERR_OFFER_NOT_ACTIVE` | 409 |
| `ERR_LISTING_NOT_OPEN` | 409 |
| `ERR_CARRIER_SUSPENDED` | 409 |
| `ERR_EQUIPMENT_MISMATCH` | 409 |
| `ERR_INSURANCE_EXPIRED` | 409 |
| `ERR_INSURANCE_INADEQUATE` | 409 |
| `ERR_PICKUP_ETA_OUT_OF_WINDOW` | 422 |
| `ERR_TERMINAL_SLOT_CONFLICT` | 409 |
| `ERR_CARRIER_SCHEDULE_CONFLICT` | 409 |
| `ERR_ASSIGNMENT_NOT_DISPATCHED` | 409 |
| `ERR_ALREADY_PICKED_UP` | 409 |
| `ERR_DUPLICATE_INSPECTION` | 409 |
| `ERR_BALANCE_OUTSTANDING` | 409 |
| `ERR_OPEN_CLAIM` | 409 |
| `ERR_CLAIM_NOT_ACTIONABLE` | 409 |
| `ERR_NO_DAMAGE_ON_RECORD` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_MC_NUMBER` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
