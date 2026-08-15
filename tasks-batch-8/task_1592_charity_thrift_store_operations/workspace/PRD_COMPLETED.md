# Charity Thrift Store API — Product Requirements Document

## 1. Introduction

A charity thrift store in the Goodwill/ReStore mold earns mission revenue twice from the same donated goods: once on the sales floor, and again — for what never sells — through salvage commodity buyers who pay by the pound. Between those two revenue moments sits a demanding daily operation: donations arrive at the intake desk and on scheduled truck routes, every item must be triaged into a salable, recyclable, or disposable stream, sellable goods are priced against store guidelines and rotated through a weekly color-tag markdown cadence, registers are opened and blind-counted under segregation of duties, donors expect compliant tax receipts, and each closed week's net revenue must be split between an operating reserve and the charity's mission programs.

This document specifies the API that runs that operation end to end. It coordinates eight distinct operator roles across the donation pipeline, the sales floor, the till, the truck, the volunteer roster, and the back office; it encodes the compliance thresholds that govern receipt issuance; and it treats the weekly cycle as the store's fiscal heartbeat, closing each week with a revenue and shrink snapshot that seeds the next week's merchandising posture. The requirements below are written for the engineering team building the service: §2 states the system-wide contracts, §3 walks the business workflows, §4 summarizes the HTTP contract, and §5 catalogs the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly eight roles: `StoreManager`, `IntakeAttendant`, `Pricer`, `Cashier`, `Driver`, `Volunteer`, `VolunteerCoordinator`, and `FinanceClerk`. A request missing either header, or presenting an `X-User-Role` value outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the target endpoint's authorization list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Three of the eight roles are entity-backed by the Worker register. When `X-User-Role` is `Cashier`, `Driver`, or `Volunteer`, `X-User-ID` is the `id` of the acting `Worker`; ownership checks on any resource that references a Worker compare the resource's foreign-key field to `X-User-ID` — `cashier_worker_id` on a till session for a Cashier, `driver_worker_id` on a pickup route for a Driver, and `worker_id` on a shift assignment for a Volunteer — with mismatches rejected as `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). The remaining five roles are opaque: when `X-User-Role` is `StoreManager`, `IntakeAttendant`, `Pricer`, `VolunteerCoordinator`, or `FinanceClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `counted_by_user_id` on a till session, `prepared_by_user_id` on a mission transfer, or `voided_by_user_id` on a voided sale) but never compares it to any entity's `id`.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer value for either parameter, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order, with ties on `created_at` broken by `id`. Paginated list responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more` — `has_more` is true exactly when `offset` plus the number of items returned is smaller than `total_count`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource the API persists — donors, donation batches, donation items, pricing guidelines, salvage vendors, salvage bales, sales transactions, till sessions, pickup routes, pickup stops, workers, shifts, shift assignments, weekly cycles, mission transfers, and tax receipts — carries a common set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` records the ISO 8601 UTC timestamp of creation with three fractional digits; `updated_at` refreshes on every mutation. The `version` is an integer starting at 1 that increments by one on every mutation of the resource — including mutations the server applies as side effects of operations on other resources, so adding an item to a batch, selling an item out of a batch, or creating a transfer against a cycle each bump the owning resource's `version` and refresh its `updated_at`.

### 2.5. The Store's Logical Clock

All timestamps the system assigns — `opened_at`, `closed_at`, `priced_at`, `sold_at`, `sealed_at`, `shipped_at`, `settled_at`, `issued_at`, `voided_at`, `disbursed_at`, and computed deadlines such as `hold_expires_at` — read a single logical clock, never wall-clock time. Before any client call, the clock reads exactly 2026-08-01T00:00:00Z. A StoreManager-only test-driving capability, `POST /api/_clock/set_current_utc`, sets the logical clock to a supplied `to_iso8601` instant — any valid ISO 8601 instant is accepted, whether ahead of or behind the current reading — and answers with the resulting `current_utc`; every subsequent system timestamp uses the new clock.

### 2.6. Monetary Representation, Precision, and Rounding

All monetary values in the system — prices, provisional values, sale totals, till figures, bale revenues, receipt totals, and transfer amounts — are represented as integer cents. Unless a rule states otherwise, every monetary calculation rounds half up to whole cents at the step the rule specifies. Two deliberate exceptions exist: mission-transfer allocation lines round half DOWN (with the unallocated remainder assigned to the last line, §3.9), and worker shift hours are carried at two decimal places rounded half up (§3.8). The weekly shrink rate is expressed as a whole number of basis points, rounded half up. Hours, volumes, and weights keep their natural decimal precision.

### 2.7. The Weekly Merchandising Cycle and Tag Rotation

Store merchandising runs on weekly cycles, and at most one WeeklyCycle may be OPEN at any moment: attempting to open a cycle while another is OPEN is rejected with `ERR_CYCLE_INVALID_STATE`. Each cycle carries a 1-based `sequence_number` that increments per cycle, and a `rotation_color` derived from that sequence: a sequence number whose remainder when divided by four is 1 rotates `RED`, remainder 2 rotates `BLUE`, remainder 3 rotates `GREEN`, and a sequence number exactly divisible by four rotates `YELLOW`. Every item moved to the floor during a cycle is stamped with that cycle's identity and color, and the color cadence drives the weekly markdown run described in §3.4 — each cycle permits exactly one markdown run.

A cycle also opens with a `shrink_alert_active` posture copied forward from the previous cycle's close: the posture is on when the previous cycle's computed shrink rate reached the alert threshold defined in §3.4, and the very first cycle opens with the posture off. While a cycle's shrink alert is active, pricing high-value items is reserved for managers (§3.3).

### 2.8. Optimistic Concurrency Control

Two write operations guard against stale reads with optimistic concurrency control, and both treat their expected-version field as a required input. All other endpoints take no version field.

- **Batch revalue.** A revalue request must carry `expected_batch_version` holding the batch `version` the client last observed. If the batch's current `version` has advanced beyond that value — because items were added, triaged, repriced, or otherwise mutated since — the revalue is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412). Revalue legitimately supersedes prior valuations (latest wins), so a writer holding a stale version would silently discard intervening intake mutations it never observed.
- **Mission-transfer creation.** A request creating a mission transfer for a cycle must carry `expected_cycle_version` holding the cycle `version` the client last observed. A mismatch with the cycle's current `version` is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). A new draft transfer legitimately supersedes the cycle's existing draft, so a writer holding a stale version would supersede a transfer it never saw.

### 2.9. Validation Order and Error Precedence

When a request violates several rules at once, a fixed priority order decides which rejection the client sees — lower tiers are evaluated before higher ones:

1. **Authentication** — headers present and the role recognized, else `ERR_UNAUTHENTICATED`.
2. **Request schema** — required fields present, types valid, enum values within their declared domains, unknown fields rejected, required arrays non-empty (`item_ids` on a sale), time windows ordered (`window_end` strictly after `window_start`, `ends_at` strictly after `starts_at`), and amounts non-negative — violations yield `ERR_INVALID_REQUEST`. Two endpoints defer parts of this tier past their stale-version check: on a revalue and on a mission-transfer creation, the array non-emptiness check and all per-entry validation of `adjustments`/`allocations` run only after the tier-7 version comparison (§3.1, §3.9).
3. **Role authorization** — the role must appear in the endpoint's authorization list, else `ERR_UNAUTHORIZED`.
4. **Existence** — path identifiers resolve left to right, then body references (`donor_id`, `worker_id`, `till_session_id`, every element of `item_ids`, `vendor_id`, `target_route_id`, every adjustment's `item_id`); the first unresolvable identifier yields `ERR_NOT_FOUND`. Two body references defer past this tier with their sibling schema checks: on a bale seal the `vendor_id` resolves only after the bale's `ACCUMULATING` from-state check (§3.5), and on a revalue each adjustment's `item_id` resolves only after the stale-version check (§3.1). The path identifiers used across the API are `donor_id`, `batch_id`, `item_id`, `guideline_id`, `vendor_id`, `bale_id`, `session_id`, `sale_id`, `route_id`, `stop_id`, `worker_id`, `shift_id`, `assignment_id`, `cycle_id`, `transfer_id`, and `receipt_id`.
5. **Ownership** — entity-backed identity must match the resource's owner field, else `ERR_FORBIDDEN_OWNERSHIP`.
6. **State preconditions** — the target resource must be in the from-state of the attempted transition. Each resource family reports its own state error: `ERR_BATCH_INVALID_STATE`, `ERR_ITEM_INVALID_STATE`, `ERR_TILL_INVALID_STATE`, `ERR_SALE_INVALID_STATE`, `ERR_ROUTE_INVALID_STATE`, `ERR_STOP_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_CYCLE_INVALID_STATE`, `ERR_TRANSFER_INVALID_STATE`, `ERR_RECEIPT_INVALID_STATE`, or `ERR_BALE_INVALID_STATE`. Sibling checks sharing this tier include `ERR_BATCH_HAS_UNTRIAGED_ITEMS`, `ERR_TILL_SESSIONS_UNCLOSED`, `ERR_BATCH_RECEIPT_MISSING`, and `ERR_REVALUE_BLOCKED_BY_RECEIPT`.
7. **Stale-version (OCC) checks**, evaluated only after state preconditions pass — `ERR_STALE_BATCH_VERSION` and `ERR_STALE_CYCLE_VERSION`.
8. **Business-safety rules** — the receipt compliance gates (which have their own fixed sub-order: receipt-requested first, then appraisal confirmation, then donor address; §3.9), the two segregation-of-duties checks (§2.10), and the shrink-alert pricing gate (§3.3).
9. **Business constraints** — uniqueness rules (one OPEN till session per cashier, `ERR_TILL_SESSION_OPEN_EXISTS`; one OPEN cycle; one ISSUED receipt per batch), capacity rules (`ERR_SHIFT_FULL`, `ERR_ROUTE_CAPACITY_EXCEEDED`), the transitional weekly hour cap (`ERR_WEEKLY_HOURS_EXCEEDED`), the transfer allocation sum (`ERR_ALLOCATION_SUM_INVALID`), the bale seal weight (`ERR_BALE_UNDERWEIGHT`), and route-publish non-emptiness (`ERR_ROUTE_EMPTY`).
10. **Temporal rules** — stop window buffers (`ERR_STOP_WINDOW_CONFLICT`), stop sequencing (`ERR_STOP_OUT_OF_SEQUENCE`), the sale void window (`ERR_SALE_VOID_WINDOW_CLOSED`), and worker double-booking (`ERR_SHIFT_OVERLAP`).
11. **Referential eligibility** — `ERR_DONOR_INACTIVE`, `ERR_WORKER_NOT_ACTIVE`, `ERR_WORKER_CAP_REACHED`, `ERR_DRIVER_NOT_STAFF`, `ERR_VENDOR_RATE_MISSING`, `ERR_GUIDELINE_MISSING`, and the open-cycle requirement `ERR_NO_OPEN_CYCLE`.

Three consequences of this ordering are worth calling out. A void attempted on a sale that is already VOIDED reports `ERR_SALE_INVALID_STATE` even when the void window has also closed, because the state tier outranks the temporal tier. Sealing an underweight bale reports `ERR_BALE_UNDERWEIGHT` even when the named vendor also declares no rates for the bale's category — the weight check is always evaluated before vendor checks. And a conflicting stop window surfaces as `ERR_STOP_WINDOW_CONFLICT` even when the referenced donor is also inactive, because the temporal tier outranks referential eligibility.

### 2.10. Segregation of Duties in Cash and Funds Handling

Cash and mission funds are divided so that no single operator controls a control point end to end. A cashier never reconciles their own drawer: blind counts are exclusively a `StoreManager` duty. When a count lands outside the auto-reconcile band, the `FinanceClerk` approving the variance must not be the manager who entered the count — the approver's `X-User-ID` must differ from the session's `counted_by_user_id`, or the approval is rejected with `ERR_SOD_APPROVER_IS_COUNTER` (HTTP 422). Mission transfers split preparation from approval the same way: the `StoreManager` approving a transfer must differ from the `FinanceClerk` recorded as `prepared_by_user_id`, or the approval is rejected with `ERR_SOD_APPROVER_IS_PREPARER` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Donor Registration and Donation Batch Intake

An `IntakeAttendant` registers each donor with a `full_name`; the contact fields `email`, `address_line`, `city`, `state`, and `postal_code` are optional at registration, though the address becomes mandatory later for larger receipts (§3.9). A new donor starts with `status` `ACTIVE`, `tier` `STANDARD`, and a `lifetime_donation_count` of zero. The attendant may later update any of the contact fields or toggle `status` between `ACTIVE` and `INACTIVE`; either change bumps the donor's `version`. An `INACTIVE` donor cannot open a donation batch and cannot be scheduled onto a pickup stop — both attempts are rejected with `ERR_DONOR_INACTIVE`. Donors graduate to the `FREQUENT` tier automatically once their `lifetime_donation_count` reaches ten batches (§3.9 shows where the count increments).

Donations enter the store as batches. Opening a batch takes the `donor_id`, a `source` of `WALK_IN` or `DONATION_DRIVE`, and an optional `receipt_requested` flag (default false) recording whether the donor wants a tax receipt; the third source value, `PICKUP_STOP`, is system-set only and marks the batches a truck route creates automatically (§3.7) — posting a batch with `source` `PICKUP_STOP` is rejected with `ERR_INVALID_REQUEST`. A new batch opens in `OPEN` status with `item_count`, `untriaged_count`, `provisional_value_cents`, and `sold_item_count` all at zero. The batch list supports filtering by `donor_id`, `pickup_stop_id`, or `status`.

While a batch is `OPEN`, the attendant adds items to it one call at a time, supplying a `category` (`CLOTHING`, `FURNITURE`, `ELECTRONICS`, `HOUSEWARES`, `BOOKS_MEDIA`, `TOYS`, or `COLLECTIBLES`), a `condition` (`NEW_WITH_TAGS`, `GOOD`, `FAIR`, or `POOR`), and optionally a free-text `description` and a `weight_lbs`. Adding an item to a batch that is no longer `OPEN` fails with `ERR_BATCH_INVALID_STATE`. Each item is born in `RECEIVED` status, stamped with its owning batch's `batch_id`, and immediately carries a `provisional_value_cents`: the fair-market figure for its category — 800 cents for CLOTHING, 4500 for FURNITURE, 3000 for ELECTRONICS, 1200 for HOUSEWARES, 300 for BOOKS_MEDIA, 600 for TOYS, 5000 for COLLECTIBLES — multiplied by the condition's value factor (1.0 for NEW_WITH_TAGS, 0.7 for GOOD, 0.4 for FAIR, 0.15 for POOR), rounded half up to whole cents. This provisional figure deliberately ignores the store's pricing guidelines; it is the valuation basis for tax receipts, not the sell price. Every added item recomputes the batch's `item_count`, `untriaged_count`, and `provisional_value_cents` — the last being the sum over all of the batch's items — and bumps the batch's `version`.

Intake valuation can be corrected afterwards through the batch revalue operation, which takes `expected_batch_version` (§2.8) and a non-empty `adjustments` array whose entries each reference an item of the batch by `item_id` and supply that item's replacement `provisional_value_cents`. The latest revalue supersedes prior ones, overwriting the named items' provisional values and recomputing the batch total. Revalue is forbidden once the batch is `CLOSED` or `CANCELLED` (`ERR_BATCH_INVALID_STATE`), and forbidden while an ISSUED tax receipt exists for the batch (`ERR_REVALUE_BLOCKED_BY_RECEIPT`). Per §2.9's deferral note, the checks run in this order: the state and receipt gates, then the `expected_batch_version` comparison, and only then the array non-emptiness check, per-entry shape validation, and resolution of each adjustment's `item_id` (an id that does not resolve to an item of this batch yields `ERR_NOT_FOUND` at that point).

A batch that was opened in error can be abandoned: cancelling moves `OPEN` → `CANCELLED`, but only while the batch still holds zero items — cancelling once `item_count` has grown fails with `ERR_BATCH_INVALID_STATE`. Both the cancellation and every other batch mutation bump the batch's `version`.

### 3.2. Sorting and Triage: The Salable / Recycle / Salvage Fork

Once a batch holds at least one item, the attendant begins sorting, moving the batch `OPEN` → `SORTING`; an empty batch cannot begin sorting (`ERR_BATCH_INVALID_STATE`). Sorting is where every item meets its fork. Triage takes a `decision` of `SALABLE`, `RECYCLE`, or `SALVAGE` and is accepted only while the owning batch is `SORTING` — triaging against a batch in any other state fails with `ERR_BATCH_INVALID_STATE`. The item's own from-state is verified first: triaging an item that is not `RECEIVED` fails with `ERR_ITEM_INVALID_STATE`, ahead of the batch's `SORTING` precondition. Whichever branch is taken, the triage decrements the batch's `untriaged_count` and bumps its `version`.

- A `SALABLE` decision sends the item toward pricing. The triage payload may also set `appraisal_confirmed` (default false); attendants set it on high-value items, and receipt issuance later blocks on it (§3.9).
- A `RECYCLE` decision commits the item to the salvage stream by weight. The payload must name a `salvage_category` — `TEXTILES`, `PAPER`, `EWASTE`, or `BULK` — and a `weight_lbs` must be on record for the item, supplied either in the triage payload or back at intake; either omission fails with `ERR_INVALID_REQUEST`. The weight must be positive — a zero or negative figure fails with `ERR_INVALID_REQUEST` — and a payload `weight_lbs` supersedes the intake value stored on the item. The item then feeds its salvage category's `ACCUMULATING` bale: if no such bale exists the system creates one on the spot, the bale's `item_count` grows by one and its `weight_lbs` by the item's weight, the item's `bale_id` is pointed at the bale, and the bale's `estimated_revenue_cents` is recomputed at default commodity rates (§3.5).
- A `SALVAGE` decision consigns the item to the salvage stream without baling; such items wait in `SALVAGE` status until the weekly cycle close disposes of them (§3.4).

When no item of the batch remains in `RECEIVED`, completing the sort moves the batch `SORTING` → `SORTED`. Completing while any item is still untriaged — while `untriaged_count` is above zero — fails with `ERR_BATCH_HAS_UNTRIAGED_ITEMS`. From `SORTED` the batch can be receipted and then closed (§3.9).

For reference as the workflows unfold, the full item state vocabulary is: `RECEIVED`, `SALABLE`, `PRICED`, `ON_FLOOR`, `ON_HOLD`, `SOLD`, `RECYCLE`, `PULLED_TO_SALVAGE`, `BALED`, `SALVAGE`, `DISPOSED`, and `SHRUNK`. Of these, `BALED`, `DISPOSED`, and `SHRUNK` are terminal; `SOLD` is reversible through a sale void (§3.6).

### 3.3. Pricing Guidelines, Item Pricing, and Floor Merchandising

Sell prices come from per-category pricing guidelines, published by a `StoreManager` with a `category`, a `base_cents` greater than zero, and an optional `demand_multiplier` (default 1.0, and it must be greater than zero). Guidelines are self-superseding: publishing a guideline for a category retires the category's prior `ACTIVE` guideline — the old row's `status` becomes `RETIRED`, the new row's `supersedes_id` points back at the old one, and `version_no` continues the per-category sequence (the first guideline ever published for a category is 1) — so exactly one `ACTIVE` guideline exists per category at any time. The guideline list supports filtering by `category`, `status`, or `supersedes_id`.

Pricing moves a `SALABLE` item to `PRICED` and may be performed by a `Pricer` or a `StoreManager`. The computation reads the `ACTIVE` guideline for the item's category; if none exists, pricing fails with `ERR_GUIDELINE_MISSING`. The price is built as follows. Start from the condition's price multiplier — 1.0 for NEW_WITH_TAGS, 0.8 for GOOD, 0.6 for FAIR, 0.35 for POOR — except that COLLECTIBLES items never price below a multiplier of 1.2, so a collectibles multiplier that falls under 1.2 is raised to 1.2. Multiply the guideline's `base_cents` by that multiplier and by the guideline's `demand_multiplier`. Clamp the product so it is never below 100 cents and never above 500000 cents, then round half up to whole cents. The result is stamped as both `base_price_cents` and `current_price_cents`, with `priced_at` set from the clock and `markdown_round` reset to 0. This priced figure is intentionally a different number from the intake provisional value — a GOOD clothing item under a guideline with `base_cents` 2000 prices at 1600 cents, while its provisional value was computed as 560.

One safety gate applies at pricing time. When the open weekly cycle's `shrink_alert_active` posture is on and the computed price comes to at least 10000 cents, only a `StoreManager` may complete the pricing; a `Pricer` attempting it is turned away with `ERR_HIGH_VALUE_NEEDS_MANAGER`. The `ACTIVE`-guideline lookup necessarily runs before this gate, since the gate reads the computed price; pricing itself never requires an open cycle — with no cycle OPEN the gate simply does not apply.

A priced item reaches the sales floor when a `Pricer` moves it `PRICED` → `ON_FLOOR`. The move requires an OPEN weekly cycle — with none, it fails with `ERR_NO_OPEN_CYCLE` — and stamps the item's `floor_cycle_id` with the open cycle's identity and its `tag_color` with that cycle's `rotation_color` (`RED`, `BLUE`, `GREEN`, or `YELLOW`). Floor staff can pull an item aside for a customer: holding moves `ON_FLOOR` → `ON_HOLD` and sets `hold_expires_at` to 72 hours from the clock, and releasing the hold returns the item `ON_HOLD` → `ON_FLOOR` with `hold_expires_at` cleared. Holds matter twice downstream: an `ON_HOLD` item cannot be sold, and a hold whose expiry has passed is auto-released — exempt from that run's markdown — at the next markdown run (§3.4).

A `StoreManager` can write off an item from `SALABLE`, `PRICED`, `ON_FLOOR`, or `ON_HOLD` by recording a shrink event, supplying a `reason` of `THEFT`, `DAMAGE`, or `LOSS` that is stored as the item's `shrink_reason`. Shrinking requires an OPEN weekly cycle (`ERR_NO_OPEN_CYCLE` otherwise) and moves the item to `SHRUNK`. The write-off snapshots `value_at_shrink_cents` — the item's `current_price_cents` when one is set, otherwise its `provisional_value_cents` — attributes the loss to the open cycle through `shrunk_cycle_id`, and clears any pending hold expiry. Attempting any of these item actions from the wrong state fails with `ERR_ITEM_INVALID_STATE`. The item list supports filtering by `batch_id`, `sale_id`, `bale_id`, `floor_cycle_id`, `shrunk_cycle_id`, `status`, or `category`.

### 3.4. The Weekly Markdown Run and Cycle Close

The first weekly cycle is opened explicitly by a `StoreManager`; every later cycle is spawned by the close of its predecessor. Opening a cycle sets `status` OPEN, stamps `opened_at` from the clock, assigns `sequence_number` one beyond the previous cycle (the first cycle is 1), and derives the `rotation_color` from the sequence per §2.7. The cycle list supports filtering by `status` — filtering for OPEN is how clients find the current cycle after a close spawns it.

Once per cycle, a `StoreManager` may run the markdown cadence against the OPEN cycle. A cycle whose `markdown_runs_count` already stands at 1 refuses a second run, and a CLOSED cycle refuses any run — both as `ERR_CYCLE_INVALID_STATE`. The run executes three steps in order:

1. **Hold auto-release.** Every item `ON_HOLD` whose `hold_expires_at` has been reached by the clock returns `ON_HOLD` → `ON_FLOOR` with the expiry cleared. Auto-released items are exempt from the rest of this run entirely — their round does not advance, and they are not pulled to salvage in this run even if their `markdown_round` already stands at 3.
2. **Markdown.** Every item still `ON_FLOOR` that was floored in an earlier cycle — its floor cycle's `sequence_number` strictly less than the running cycle's — and whose `markdown_round` is below 3 advances one round, and its `current_price_cents` is recomputed as its `base_price_cents` reduced by the entering round's discount: 25 percent off the base price at round 1, 50 percent off at round 2, and 75 percent off at round 3, rounded half up to whole cents. Items floored in the running cycle itself are never touched by the run, whatever their round.
3. **Salvage pull.** Every item `ON_FLOOR` from an earlier cycle whose `markdown_round` has already reached 3 is not re-priced; it leaves the floor for good, moving to `PULLED_TO_SALVAGE`. Eligibility for both step 2 and step 3 is snapshotted before the run mutates any item (excluding the items auto-released in step 1), so an item whose round advances to 3 during this run is pulled only by a later run, never by this one. The pull derives the item's `salvage_category` from its `category` through the category-to-salvage mapping — CLOTHING → TEXTILES, BOOKS_MEDIA → PAPER, ELECTRONICS → EWASTE, and FURNITURE, HOUSEWARES, TOYS, and COLLECTIBLES → BULK — defaults its `weight_lbs` from the category average-weight table when the item carries none (CLOTHING 1.0, FURNITURE 50.0, ELECTRONICS 10.0, HOUSEWARES 5.0, BOOKS_MEDIA 2.0, TOYS 3.0, COLLECTIBLES 5.0 pounds), and feeds the item into that salvage category's `ACCUMULATING` bale exactly as a RECYCLE triage would — auto-creating the bale when none exists, growing its `item_count` and `weight_lbs`, setting the item's `bale_id`, and recomputing the bale's estimate.

The run then sets the cycle's `markdown_runs_count` to 1 and bumps the cycle's `version`.

Closing the OPEN cycle is the week's fiscal checkpoint, again a `StoreManager` action. Close is blocked while any till session remains `OPEN`, `PENDING_APPROVAL`, or `RECONCILED` — every drawer must reach `CLOSED` first, or the close fails with `ERR_TILL_SESSIONS_UNCLOSED`. On close, the system first disposes of every item still sitting in `SALVAGE`, moving each to `DISPOSED`; stamps `closed_at`; and snapshots the week's figures. `gross_sales_cents` is the sum of `total_cents` over sales COMPLETED with `created_at` inside the half-open window from `opened_at` up to but not including `closed_at` — a sale made exactly at `opened_at` counts, one made exactly at `closed_at` does not, and VOIDED sales never count. `salvage_revenue_cents` is the sum of `settled_revenue_cents` over bales whose `settled_cycle_id` is this cycle. `net_revenue_cents` is the sum of those two. `shrink_value_cents` is the sum of `value_at_shrink_cents` over items whose `shrunk_cycle_id` is this cycle. And `shrink_rate_bp` is the shrink value multiplied by ten thousand and divided by the sum of the shrink value and gross sales, rounded half up to a whole basis point — or zero when that denominator is zero.

The close then spawns the next cycle: sequence number advanced by one, rotation color advanced accordingly, status OPEN, `opened_at` from the clock, and `shrink_alert_active` copied from the closing cycle's posture test — true when the closing cycle's `shrink_rate_bp` is at least 300 basis points, with a rate of exactly 300 triggering the alert. The closing cycle's own `version` bumps as well.

### 3.5. Salvage Bales and Vendor Settlement

Salvage vendors are registered by a `StoreManager` with a `name` and a `rates` sheet: for each salvage category the vendor buys, a list of marginal brackets in ascending order, each bracket carrying an `up_to_lbs` ceiling — the final bracket's ceiling is null, meaning unbounded — and a `rate_cents_per_lb`.

Bales themselves are never created directly. The system maintains one `ACCUMULATING` bale per salvage `category`, auto-created the first time an item is assigned to that category — by RECYCLE triage or by a markdown pull alike — and accumulating `weight_lbs` and `item_count` as items arrive. The bale list supports filtering by `category`, `status`, `vendor_id`, or `settled_cycle_id`.

While a bale accumulates, its `estimated_revenue_cents` is a standing guess priced at default commodity rates: the bale's `weight_lbs` multiplied by 12 cents per pound for TEXTILES, 6 for PAPER, 3 for EWASTE, or 2 for BULK, rounded half up to whole cents.

Sealing is a `StoreManager` action on an `ACCUMULATING` bale — sealing, shipping, or settling from any other from-state fails with `ERR_BALE_INVALID_STATE` — and takes a `vendor_id`. Two checks gate the seal, always in this order: first the bale's `weight_lbs` must be at least 100.0 pounds, with exactly 100.0 allowed to seal, else the seal fails with `ERR_BALE_UNDERWEIGHT`; then the referenced vendor must declare rates for the bale's category, else the seal fails with `ERR_VENDOR_RATE_MISSING`. The vendor reference itself is resolved only after the bale's `ACCUMULATING` from-state check — a `vendor_id` that resolves to nothing yields `ERR_NOT_FOUND`, and only an existing vendor with no rates for the bale's category yields `ERR_VENDOR_RATE_MISSING`. A successful seal records the vendor, sets `sealed_at`, and refreshes `estimated_revenue_cents` using the vendor's own sheet: the single bracket rate whose range contains the bale's total weight is applied to the whole weight, rounded half up. The seal also cascades every assigned item in `RECYCLE` or `PULLED_TO_SALVAGE` — every item whose `bale_id` is this bale — to `BALED`.

Shipping a `SEALED` bale moves it `SEALED` → `SHIPPED` and stamps `shipped_at`. Settlement is a `FinanceClerk` action on a `SHIPPED` bale, moves it `SHIPPED` → `SETTLED`, takes the scale-reported `actual_weight_lbs`, and requires an OPEN weekly cycle to attribute the revenue to (`ERR_NO_OPEN_CYCLE` otherwise). Settlement revenue walks the vendor's brackets for the bale's category in ascending order: the pounds falling into each bracket are the smaller of the remaining weight and that bracket's width; each bracket's line amount is those pounds multiplied by the bracket's rate, rounded half up to whole cents before the next bracket is computed; and `settled_revenue_cents` is the sum of those per-bracket rounded lines. The alternative order — multiplying everything first and rounding once at the end — is rejected: an EWASTE bale at 101.0 actual pounds under rates of 3.353 then 2.30 cents per pound settles at 337 cents (335 from the first bracket line plus 2 from the second), not the 338 a single final rounding would produce. Estimate and settlement genuinely diverge by design: a TEXTILES bale at 2500 pounds under a 12/10/8 bracket sheet reads a post-seal estimate of 20000 cents but settles at 25000. Settlement stamps `settled_at`, records the open cycle's identity as `settled_cycle_id`, and the bale's revenue joins that cycle's `salvage_revenue_cents` when the cycle closes (§3.4).

### 3.6. Register Operations: Till Sessions, Sales, and Voids

A `Cashier` begins a shift by opening a till session with an `opening_float_cents` of zero or more. The session's `cashier_worker_id` is taken from the acting cashier's `X-User-ID`, never from the payload, and a cashier may hold at most one OPEN session — a second open attempt fails with `ERR_TILL_SESSION_OPEN_EXISTS`. A new session is `OPEN`, stamps `opened_at`, starts `cash_sales_cents` and `card_sales_cents` at zero, and sets `expected_cash_cents` equal to the opening float. The session list supports filtering by `cashier_worker_id` or `status`.

Ringing a sale takes the `till_session_id`, a non-empty `item_ids` array, and a `payment_method` of `CASH` or `CARD`. The named session must be OPEN and owned by the acting cashier: a sale attempted on a session in any other state fails with `ERR_TILL_INVALID_STATE`, and a cashier ringing on another worker's session fails with `ERR_FORBIDDEN_OWNERSHIP`. Every listed item must be `ON_FLOOR`; anything else — including an item `ON_HOLD` — fails with `ERR_ITEM_INVALID_STATE`. The sale's `total_cents` is the sum of the lines' `current_price_cents`, with no further rounding since those prices are already markdown-rounded, and `line_count` records the number of lines. Completion moves each item to `SOLD`, stamping `sale_id` and `sold_at`; bumps each item's batch `sold_item_count` by one and that batch's `version` — a batch contributing several lines to the same sale still bumps its `version` only once per sale; adds the total to the session's `cash_sales_cents` for a CASH sale or `card_sales_cents` for a CARD sale; and recomputes `expected_cash_cents` as the opening float plus the cash-sales total. Only COMPLETED sales feed these session totals — a voided sale's total is fully removed. The sales list supports filtering by `till_session_id` or `status`.

A void compensates a COMPLETED sale, moving it to `VOIDED`; attempting one on a sale that is not COMPLETED fails with `ERR_SALE_INVALID_STATE`, and this state check outranks the window check below (§2.9). A `Cashier` may void only while the sale's session is still OPEN and their own — violations surface as `ERR_TILL_INVALID_STATE` or `ERR_FORBIDDEN_OWNERSHIP` — while a `StoreManager` may void so long as the session is anything short of CLOSED. Independently, the void window requires the clock's UTC date to equal the sale's `created_at` UTC date and the session to be not CLOSED; a void attempted on a later UTC date, or after the session has closed, fails with `ERR_SALE_VOID_WINDOW_CLOSED`. The void records `voided_by_user_id`, `voided_at`, and an optional `reason` stored as the sale's `void_reason`. Its compensation cascade then runs: every line item returns `SOLD` → `ON_FLOOR` with `current_price_cents` and `markdown_round` restored exactly as they stood at sale time (both are immutable while an item is SOLD) and its `sale_id` and `sold_at` cleared; each restored item's batch `sold_item_count` drops by one and that batch's `version` bumps (again once per batch per void, however many lines it contributed); the session's cash or card total falls by the sale's `total_cents` according to its payment method; and `expected_cash_cents` is recomputed.

End of shift brings the blind count: a `StoreManager` enters `counted_cash_cents` against an OPEN session — counting a session in any other state fails with `ERR_TILL_INVALID_STATE`. The session stores the count, records the counter's identity in `counted_by_user_id`, computes `over_short_cents` as the counted amount minus `expected_cash_cents` (a negative figure means the drawer is short), and branches on the absolute size of the discrepancy. A discrepancy of at most 500 cents in either direction — exactly 500 over or under included — reconciles immediately, moving the session `OPEN` → `RECONCILED`. A discrepancy of 501 cents or more routes the session `OPEN` → `PENDING_APPROVAL`, where it waits for a `FinanceClerk` to approve the variance. Approval moves `PENDING_APPROVAL` → `RECONCILED`, records `variance_approved_by_user_id`, and enforces segregation of duties: the approver must differ from `counted_by_user_id`, else `ERR_SOD_APPROVER_IS_COUNTER`. Approving a session that is not `PENDING_APPROVAL` fails with `ERR_TILL_INVALID_STATE`. Finally, closing moves a `RECONCILED` session to `CLOSED` and stamps `closed_at` — and recall from §3.4 that the weekly cycle cannot close while any session still sits short of `CLOSED`.

### 3.7. Donation Pickup Routes and Stops

Large-item donations arrive by truck. A `StoreManager` plans a route with a `route_date` (an ISO calendar date in YYYY-MM-DD form), a `driver_worker_id`, and the truck's `truck_capacity_cuft`, which must be greater than zero. The referenced driver must be an ACTIVE worker whose `employment_type` is `STAFF` — volunteers and transitional-employment participants never drive — or creation fails with `ERR_DRIVER_NOT_STAFF`. A new route starts `DRAFT` with `stop_count` and `total_volume_cuft` at zero. The route list supports filtering by `driver_worker_id` or `status`.

Stops join a route while it is `DRAFT`; adding a stop to a route in any other state fails with `ERR_ROUTE_INVALID_STATE`. Each stop names a `donor_id` — the donor must be ACTIVE, else `ERR_DONOR_INACTIVE` — a promised pickup window from `window_start` to `window_end`, and an `estimated_volume_cuft` greater than zero. Two constraints guard every booking. Capacity: the route's `total_volume_cuft` plus the new stop's estimate must not exceed the truck's capacity, with a stop that fills the truck exactly allowed; overflow fails with `ERR_ROUTE_CAPACITY_EXCEEDED`. Spacing: against every other stop on the route still in `SCHEDULED` or `EN_ROUTE`, the new window must keep a 30-minute travel buffer on both sides — the new window must start at least thirty minutes after the existing window ends, or the existing window must start at least thirty minutes after the new window ends, with exactly thirty minutes of separation allowed; a tighter fit fails with `ERR_STOP_WINDOW_CONFLICT`. Each added stop recomputes the route's counters and bumps the route's `version`: `stop_count` counts every stop on the route whatever its status, while `total_volume_cuft` sums `estimated_volume_cuft` over the route's stops in SCHEDULED or EN_ROUTE only. The stored counters refresh only when a stop is added, when a reschedule lands a new stop on the route, or when the route is cancelled — stop status transitions (depart, complete, no-show) leave them untouched. Stops can be listed per route, or globally with filters on `donor_id`, `route_id`, `completed_batch_id`, or `status`.

Publishing requires at least one stop still `SCHEDULED` — publishing a route with none fails with `ERR_ROUTE_EMPTY` — and moves the route `DRAFT` → `PUBLISHED`. A published route can return to `DRAFT` only while every stop is still `SCHEDULED`; once any stop has departed, completed, or no-showed, unpublishing fails with `ERR_ROUTE_INVALID_STATE`. Starting the route moves `PUBLISHED` → `IN_PROGRESS`. Completing the route requires every stop terminal — `COMPLETED`, `NO_SHOW`, or `CANCELLED` — and moves `IN_PROGRESS` → `COMPLETED`, failing with `ERR_ROUTE_INVALID_STATE` while any stop is still live. Cancelling works from `DRAFT` or `PUBLISHED`, moves the route to `CANCELLED`, and cascades every `SCHEDULED` stop on it to `CANCELLED`.

On the road, stops belong to the driver. Departing for a stop moves it `SCHEDULED` → `EN_ROUTE` and requires the route to be `IN_PROGRESS` (`ERR_ROUTE_INVALID_STATE`), the caller to be the route's own driver — the acting `X-User-ID` must equal the route's `driver_worker_id`, else `ERR_FORBIDDEN_OWNERSHIP` — and the day's sequencing to be respected: every other stop on the route with an earlier `window_start` must already be terminal, or the departure fails with `ERR_STOP_OUT_OF_SEQUENCE`. These checks fire in §2.9 order: driver ownership first (a non-owner sees `ERR_FORBIDDEN_OWNERSHIP` even when the route is not `IN_PROGRESS`), then the route's `IN_PROGRESS` precondition, then the stop's `SCHEDULED` from-state (`ERR_STOP_INVALID_STATE`), then sequencing. At the curb, the driver either completes the stop or marks it a no-show; both demand the same driver ownership, and both demand the stop be `EN_ROUTE` — acting on a stop in any other state fails with `ERR_STOP_INVALID_STATE`.

Completing a stop is the cascade that ties the route back to intake: the system auto-creates a donation batch for the stop's donor with `source` `PICKUP_STOP`, `pickup_stop_id` set to the stop, `receipt_requested` true, and status `OPEN`, and records the new batch's identity on the stop's `completed_batch_id`. From there the batch flows through ordinary sorting (§3.2) — and because a receipt was requested, it cannot close without one (§3.9). Marking `EN_ROUTE` → `NO_SHOW` instead ends the stop with no batch. A no-show is terminal for the stop itself, but a `StoreManager` may reschedule from a `NO_SHOW` stop: rescheduling creates a NEW stop in `SCHEDULED` on a target route — named by `target_route_id` and required to be `DRAFT` or `PUBLISHED` — with fresh `window_start` and `window_end`, carrying over the same `donor_id` and `estimated_volume_cuft`, and running the window-conflict and capacity checks against the target route, whose counters and `version` update accordingly. No transition ever moves the original stop out of `NO_SHOW`.

### 3.8. Workforce Management: Workers, Shifts, and Hour Caps

A `VolunteerCoordinator` registers workers with a `full_name`, an `employment_type` of `VOLUNTEER`, `TRANSITIONAL`, or `STAFF`, an optional `email`, and — for transitional-employment participants — a `program_cap_hours` that defaults to 480 and must be greater than zero. Workers start `ACTIVE` with `credited_hours` at zero. The coordinator may later toggle a worker's `status` between `ACTIVE` and `INACTIVE` or update the `email`; a `StoreManager` may instead grant `cap_extension_hours` (zero or more, default 0). The role split is descriptive rather than enforced: either authorized role may set any of the mutable fields (`status`, `email`, `cap_extension_hours`) in a PATCH, and a supplied `status` is applied as given — so PATCHing `status` `ACTIVE` onto a `CAP_REACHED` worker lifts the cap state by hand (the reverse is impossible, since `CAP_REACHED` lies outside the payload enum). A worker's effective cap is `program_cap_hours` plus `cap_extension_hours`, and when an extension raises the effective cap above the worker's `credited_hours`, a `CAP_REACHED` worker automatically returns to `ACTIVE`. Every such edit bumps the worker's `version`. The third status value, `CAP_REACHED`, is never set by hand: it arrives automatically at completion time (below) and blocks further assignment — assigning an `INACTIVE` worker fails with `ERR_WORKER_NOT_ACTIVE`, and assigning a `CAP_REACHED` one fails with `ERR_WORKER_CAP_REACHED`.

Shifts are created by the coordinator with a `role_type` of `SORTER`, `PRICER`, `CASHIER`, `DRIVER`, `FLOOR`, or `INTAKE`; a `starts_at` and an `ends_at` (the end must be strictly after the start, else `ERR_INVALID_REQUEST`); and a `required_headcount` of at least one. A shift's `assigned_count` tracks seats currently held — the number of its assignments in `ASSIGNED` or `CONFIRMED`.

Assigning a worker to a shift, again the coordinator's action with the target named by `worker_id`, runs four gates, evaluated in exactly the order listed here — this per-endpoint order governs over §2.9's global tiers for these four checks. Seat capacity: `assigned_count` must still be below `required_headcount`, else `ERR_SHIFT_FULL`. Worker status, per the two errors above. Double-booking: the worker must hold no other `ASSIGNED` or `CONFIRMED` assignment whose interval overlaps the shift's interval — intervals that merely touch at an endpoint are allowed and, unlike stop windows, no buffer is added — else `ERR_SHIFT_OVERLAP`. And the transitional weekly cap: for a TRANSITIONAL worker, sum the durations of the worker's assignments in `ASSIGNED`, `CONFIRMED`, or `COMPLETED` whose shifts start in the same ISO week — the week bounded by Monday 00:00 UTC — as the new shift's `starts_at`, where each duration is the shift's length in seconds divided by 3600 and rounded half up to two decimal places; the running total plus the new shift's duration must stay at or under 20.0 hours, with exactly 20.0 allowed, else `ERR_WEEKLY_HOURS_EXCEEDED`. VOLUNTEER and STAFF workers face no weekly cap. A successful assignment starts in `ASSIGNED`, grows the shift's `assigned_count` by one, and bumps the shift's `version`. The assignment list supports filtering by `shift_id`, `worker_id`, or `status`.

Confirming an assignment moves `ASSIGNED` → `CONFIRMED`; a `Volunteer` may confirm only their own assignment — the acting `X-User-ID` must equal the assignment's `worker_id`, else `ERR_FORBIDDEN_OWNERSHIP` — while a `VolunteerCoordinator` may confirm any. Completing an assignment is the coordinator's alone and moves `CONFIRMED` → `COMPLETED`: it records `credited_hours_applied` — the shift's duration in hours at two decimal places, rounded half up — adds those hours to the worker's `credited_hours`, and frees the seat, dropping the shift's `assigned_count` by one since a completed assignment no longer holds capacity. For a TRANSITIONAL worker the credit also tests the program cap: when `credited_hours` reaches or exceeds the effective cap — landing exactly on the cap flips the worker — the worker moves automatically to `CAP_REACHED`; VOLUNTEER and STAFF workers are never capped. Marking a no-show moves an `ASSIGNED` or `CONFIRMED` assignment to `NO_SHOW` and frees the seat; cancelling — a `Volunteer` again only for their own assignment, the coordinator for any — moves `ASSIGNED` or `CONFIRMED` to `CANCELLED` and frees the seat. Acting on an assignment from the wrong state — confirming one not `ASSIGNED`, completing one not `CONFIRMED`, or no-showing or cancelling one already terminal — fails with `ERR_ASSIGNMENT_INVALID_STATE`.

### 3.9. Tax Receipts and Mission Transfers

Receipts and transfers are where the store's compliance and mission obligations settle.

A tax receipt is issued by an `IntakeAttendant` against a `SORTED` batch — issuing against a batch in any other state fails with `ERR_BATCH_INVALID_STATE` — and issuance runs three compliance gates in a fixed order. First, the batch must have been opened with `receipt_requested` true, else `ERR_RECEIPT_NOT_REQUESTED`. Second, every item in the batch whose `provisional_value_cents` is at least 500000 cents must carry `appraisal_confirmed` true — the flag captured at triage in §3.2 — else `ERR_APPRAISAL_REQUIRED`. Third, when the receipt total reaches 50000 cents the donor's `address_line` must be present, else `ERR_DONOR_ADDRESS_REQUIRED`. At most one ISSUED receipt exists per batch: issuing while one is still ISSUED fails with `ERR_RECEIPT_INVALID_STATE`.

The issued receipt carries a unique `receipt_number` of the form `RCT-%06d` — RCT- followed by a six-digit zero-padded sequence starting at 1, so the first receipt issued is `RCT-000001` — the batch's `batch_id`, a `donor_id` denormalized from the batch so donor receipt lookups need no join, an `issued_at` from the clock, and status `ISSUED`. Its `total_value_cents` is the sum of `provisional_value_cents` over ALL items of the batch, whatever disposition those items later reached. Two flags scale with that total: `itemized_required` turns true when the total reaches 25000 cents — the $250 written-acknowledgment threshold — and `form_8283_required` turns true at 50000 cents — the $500 noncash charitable threshold. The receipt list supports filtering by `batch_id`, `donor_id`, or `status`.

Closing a batch moves `SORTED` → `CLOSED` — a batch in any other state cannot close (`ERR_BATCH_INVALID_STATE`) — and the close is receipt-aware: when `receipt_requested` is true, an ISSUED receipt must already exist for the batch, or the close fails with `ERR_BATCH_RECEIPT_MISSING`. A successful close stamps `closed_at`, bumps the batch's `version`, increments the donor's `lifetime_donation_count` by one, and recomputes the donor's `tier` — `FREQUENT` once the count is at least ten, `STANDARD` below that. Closing also locks the paperwork: once the batch is `CLOSED`, voiding its receipt fails with `ERR_RECEIPT_LOCKED`. While the batch is anything short of CLOSED, a `StoreManager` may void an ISSUED receipt, stamping `voided_at` and moving it `ISSUED` → `VOIDED`; voiding a receipt that is not ISSUED fails with `ERR_RECEIPT_INVALID_STATE`.

What remains is moving the week's net revenue to the mission. A `FinanceClerk` prepares a mission transfer against a CLOSED cycle — targeting a cycle in any other state fails with `ERR_CYCLE_INVALID_STATE` — carrying `expected_cycle_version` (§2.8) and an `allocations` array. Each allocation names a `program` — `JOB_TRAINING`, `YOUTH_SERVICES`, `HOUSING_SUPPORT`, or `GENERAL_FUND` — and a `pct` greater than zero and at most 100, with up to three decimal places; the percentages across the array must sum to exactly 100, else `ERR_ALLOCATION_SUM_INVALID`. Per §2.9's deferral note, the checks run in this order: the cycle's CLOSED state gate, then the `expected_cycle_version` comparison, and only then the array non-emptiness check, the per-line program and `pct` validation, and the sum-to-100 rule. Creation supersedes the cycle's paperwork: any existing DRAFT transfer for the same cycle moves to `CANCELLED`. The creator's identity is recorded as `prepared_by_user_id`, and the creation bumps the cycle's `version` by one.

The transfer's amounts are computed in a pinned order, because the reserve tier reads the gross pool, not the net. First `gross_pool_cents` snapshots the cycle's `net_revenue_cents` at creation. Then `reserve_pct` is keyed on that gross figure: under 100000 cents the reserve is 10 percent; at least 100000 and under 500000 cents it is 15 percent; at least 500000 cents it is 20 percent. Next `reserve_cents` is the gross pool multiplied by the reserve percentage and divided by one hundred, rounded half up to whole cents, and `net_pool_cents` is the gross pool minus the reserve. Each line of `allocation_amounts` then takes the net pool multiplied by the line's `pct` and divided by one hundred, rounded half DOWN to whole cents, and whatever remainder remains after the rounded lines are summed is added to the LAST line in request order, so the lines always sum exactly to `net_pool_cents`. Keying the tier on the net instead would misprice the reserve: a gross pool of 110000 cents tiers at 15 percent — reserve 16500, net pool 93500 — where a net-keyed reading would wrongly have taken 10 percent.

Approval and disbursement split along segregation-of-duties lines. A `StoreManager` approves a DRAFT transfer — approving one in any other state fails with `ERR_TRANSFER_INVALID_STATE` — and the approver's `X-User-ID` must differ from `prepared_by_user_id`, else `ERR_SOD_APPROVER_IS_PREPARER`; approval records `approved_by_user_id` and moves the transfer `DRAFT` → `APPROVED`. A `FinanceClerk` then disburses an APPROVED transfer, stamping `disbursed_at` and moving it `APPROVED` → `DISBURSED`; disbursing from any other state is likewise `ERR_TRANSFER_INVALID_STATE`. The transfer list supports filtering by `cycle_id` or `status`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Operations that create a new resource return `201 Created`; operations that read a resource, modify it, or drive a state transition return `200 OK`. Every read endpoint authorizes all eight declared roles — `StoreManager`, `IntakeAttendant`, `Pricer`, `Cashier`, `Driver`, `Volunteer`, `VolunteerCoordinator`, and `FinanceClerk` — shown as "All roles" below; write endpoints restrict roles as listed. Request payloads, computed fields, and side effects are specified in §2 and §3; this table is the HTTP contract summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the server's logical clock (test-driving endpoint) | StoreManager |
| POST | `/api/donors` | Register a donor | IntakeAttendant |
| GET | `/api/donors/{donor_id}` | Get a donor | All roles |
| PATCH | `/api/donors/{donor_id}` | Update donor contact fields or toggle status ACTIVE/INACTIVE | IntakeAttendant |
| POST | `/api/donation-batches` | Open a donation batch at intake (donor must be ACTIVE; PICKUP_STOP source is system-only) | IntakeAttendant |
| GET | `/api/donation-batches/{batch_id}` | Get a donation batch | All roles |
| GET | `/api/donation-batches` | List/filter donation batches by donor, pickup stop, or status | All roles |
| POST | `/api/donation-batches/{batch_id}/items` | Add an item to an OPEN batch; provisional value computed at creation | IntakeAttendant |
| GET | `/api/donation-batches/{batch_id}/items` | List items of a batch | All roles |
| POST | `/api/donation-batches/{batch_id}/begin-sort` | Move batch OPEN → SORTING (requires at least one item) | IntakeAttendant |
| POST | `/api/donation-batches/{batch_id}/complete-sort` | Move batch SORTING → SORTED (requires all items triaged) | IntakeAttendant |
| POST | `/api/donation-batches/{batch_id}/revalue` | OCC-guarded valuation correction over writing items' provisional values | IntakeAttendant |
| POST | `/api/donation-batches/{batch_id}/close` | Move batch SORTED → CLOSED (receipt gate when requested) | IntakeAttendant |
| POST | `/api/donation-batches/{batch_id}/cancel` | Move batch OPEN → CANCELLED (requires zero items) | IntakeAttendant |
| POST | `/api/donation-batches/{batch_id}/receipt` | Issue the tax receipt for a SORTED batch | IntakeAttendant |
| GET | `/api/items/{item_id}` | Get an item | All roles |
| GET | `/api/items` | List/filter items by batch, sale, bale, floor cycle, shrink cycle, status, or category | All roles |
| POST | `/api/items/{item_id}/triage` | Move item RECEIVED → SALABLE / RECYCLE / SALVAGE (batch must be SORTING) | IntakeAttendant |
| POST | `/api/items/{item_id}/price` | Move item SALABLE → PRICED via the ACTIVE guideline (shrink-alert gate) | Pricer, StoreManager |
| POST | `/api/items/{item_id}/to-floor` | Move item PRICED → ON_FLOOR; stamps floor cycle and tag color | Pricer |
| POST | `/api/items/{item_id}/hold` | Move item ON_FLOOR → ON_HOLD (72-hour expiry) | Pricer |
| POST | `/api/items/{item_id}/release-hold` | Move item ON_HOLD → ON_FLOOR | Pricer |
| POST | `/api/items/{item_id}/shrink` | Write off an item to SHRUNK, attributed to the OPEN cycle | StoreManager |
| POST | `/api/pricing-guidelines` | Publish a guideline; retires the prior ACTIVE guideline for the category | StoreManager |
| GET | `/api/pricing-guidelines/{guideline_id}` | Get a pricing guideline | All roles |
| GET | `/api/pricing-guidelines` | List/filter guidelines by category, status, or supersession | All roles |
| POST | `/api/salvage-vendors` | Register a salvage vendor with per-category marginal rate brackets | StoreManager |
| GET | `/api/salvage-vendors/{vendor_id}` | Get a salvage vendor | All roles |
| GET | `/api/salvage-bales/{bale_id}` | Get a salvage bale | All roles |
| GET | `/api/salvage-bales` | List/filter bales by category, status, vendor, or settled cycle (bales are auto-created, never posted) | All roles |
| POST | `/api/salvage-bales/{bale_id}/seal` | Move bale ACCUMULATING → SEALED (weight and vendor gates; items become BALED) | StoreManager |
| POST | `/api/salvage-bales/{bale_id}/ship` | Move bale SEALED → SHIPPED | StoreManager |
| POST | `/api/salvage-bales/{bale_id}/settle` | Move bale SHIPPED → SETTLED; marginal-bracket settlement on scale weight | FinanceClerk |
| POST | `/api/till-sessions` | Cashier opens own drawer session (one OPEN session per cashier) | Cashier |
| GET | `/api/till-sessions/{session_id}` | Get a till session | All roles |
| GET | `/api/till-sessions` | List/filter till sessions by cashier or status | All roles |
| POST | `/api/till-sessions/{session_id}/count` | Manager blind count: OPEN → RECONCILED or PENDING_APPROVAL | StoreManager |
| POST | `/api/till-sessions/{session_id}/approve-variance` | Move session PENDING_APPROVAL → RECONCILED (approver differs from counter) | FinanceClerk |
| POST | `/api/till-sessions/{session_id}/close` | Move session RECONCILED → CLOSED | StoreManager |
| POST | `/api/sales` | Ring a sale on an OPEN session owned by the acting cashier; every line ON_FLOOR | Cashier |
| GET | `/api/sales/{sale_id}` | Get a sale | All roles |
| GET | `/api/sales` | List/filter sales by session or status | All roles |
| POST | `/api/sales/{sale_id}/void` | Void a COMPLETED sale within the void window; restores items to the floor | Cashier, StoreManager |
| POST | `/api/pickup-routes` | Create a DRAFT pickup route (driver must be ACTIVE STAFF) | StoreManager |
| GET | `/api/pickup-routes/{route_id}` | Get a pickup route | All roles |
| GET | `/api/pickup-routes` | List/filter routes by driver or status | All roles |
| POST | `/api/pickup-routes/{route_id}/stops` | Add a stop to a DRAFT route (window buffer, capacity, and donor checks) | StoreManager |
| GET | `/api/pickup-routes/{route_id}/stops` | List stops of a route | All roles |
| GET | `/api/pickup-stops/{stop_id}` | Get a pickup stop | All roles |
| GET | `/api/pickup-stops` | List/filter stops by donor, route, completed batch, or status | All roles |
| POST | `/api/pickup-routes/{route_id}/publish` | Move route DRAFT → PUBLISHED (requires at least one SCHEDULED stop) | StoreManager |
| POST | `/api/pickup-routes/{route_id}/unpublish` | Move route PUBLISHED → DRAFT (only while every stop still SCHEDULED) | StoreManager |
| POST | `/api/pickup-routes/{route_id}/start` | Move route PUBLISHED → IN_PROGRESS | StoreManager |
| POST | `/api/pickup-routes/{route_id}/complete` | Move route IN_PROGRESS → COMPLETED (all stops terminal) | StoreManager |
| POST | `/api/pickup-routes/{route_id}/cancel` | Move route DRAFT/PUBLISHED → CANCELLED; cascades SCHEDULED stops | StoreManager |
| POST | `/api/pickup-stops/{stop_id}/depart` | Move stop SCHEDULED → EN_ROUTE (route live, driver owns route, sequencing kept) | Driver |
| POST | `/api/pickup-stops/{stop_id}/complete` | Move stop EN_ROUTE → COMPLETED; auto-creates the donor's PICKUP_STOP batch | Driver |
| POST | `/api/pickup-stops/{stop_id}/no-show` | Move stop EN_ROUTE → NO_SHOW | Driver |
| POST | `/api/pickup-stops/{stop_id}/reschedule` | From a NO_SHOW stop, create a NEW SCHEDULED stop on a target route | StoreManager |
| POST | `/api/workers` | Register a worker (volunteer, transitional participant, or staff) | VolunteerCoordinator |
| GET | `/api/workers/{worker_id}` | Get a worker | All roles |
| PATCH | `/api/workers/{worker_id}` | Toggle ACTIVE/INACTIVE (coordinator) or grant cap-extension hours (manager) | VolunteerCoordinator, StoreManager |
| POST | `/api/shifts` | Create a shift slot with headcount capacity | VolunteerCoordinator |
| GET | `/api/shifts/{shift_id}` | Get a shift | All roles |
| POST | `/api/shifts/{shift_id}/assignments` | Assign a worker (seat capacity, overlap, weekly-cap, and status gates) | VolunteerCoordinator |
| GET | `/api/shift-assignments/{assignment_id}` | Get an assignment | All roles |
| GET | `/api/shift-assignments` | List/filter assignments by shift, worker, or status | All roles |
| POST | `/api/shift-assignments/{assignment_id}/confirm` | Move assignment ASSIGNED → CONFIRMED (Volunteer only own) | Volunteer, VolunteerCoordinator |
| POST | `/api/shift-assignments/{assignment_id}/complete` | Move assignment CONFIRMED → COMPLETED; credits hours and tests the program cap | VolunteerCoordinator |
| POST | `/api/shift-assignments/{assignment_id}/no-show` | Move assignment ASSIGNED/CONFIRMED → NO_SHOW | VolunteerCoordinator |
| POST | `/api/shift-assignments/{assignment_id}/cancel` | Move assignment ASSIGNED/CONFIRMED → CANCELLED (Volunteer only own) | Volunteer, VolunteerCoordinator |
| POST | `/api/cycles` | Open the next weekly cycle (only when no OPEN cycle exists) | StoreManager |
| GET | `/api/cycles` | List/filter cycles by status | All roles |
| GET | `/api/cycles/{cycle_id}` | Get a weekly cycle | All roles |
| POST | `/api/cycles/{cycle_id}/run-markdown` | Weekly markdown cadence (once per cycle): release holds, advance rounds, pull stale items | StoreManager |
| POST | `/api/cycles/{cycle_id}/close` | Close the cycle: dispose SALVAGE items, snapshot revenue and shrink, spawn next cycle | StoreManager |
| POST | `/api/cycles/{cycle_id}/mission-transfers` | OCC-guarded: create a DRAFT mission transfer for a CLOSED cycle; supersedes existing DRAFT | FinanceClerk |
| GET | `/api/mission-transfers/{transfer_id}` | Get a mission transfer | All roles |
| GET | `/api/mission-transfers` | List/filter mission transfers by cycle or status | All roles |
| POST | `/api/mission-transfers/{transfer_id}/approve` | Move transfer DRAFT → APPROVED (approver differs from preparer) | StoreManager |
| POST | `/api/mission-transfers/{transfer_id}/disburse` | Move transfer APPROVED → DISBURSED | FinanceClerk |
| GET | `/api/tax-receipts/{receipt_id}` | Get a tax receipt | All roles |
| GET | `/api/tax-receipts` | List/filter tax receipts by batch, donor, or status | All roles |
| POST | `/api/tax-receipts/{receipt_id}/void` | Move receipt ISSUED → VOIDED (only while the owning batch is not CLOSED) | StoreManager |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_BATCH_VERSION` | 412 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_BATCH_INVALID_STATE` | 409 |
| `ERR_BATCH_HAS_UNTRIAGED_ITEMS` | 409 |
| `ERR_BATCH_RECEIPT_MISSING` | 409 |
| `ERR_REVALUE_BLOCKED_BY_RECEIPT` | 409 |
| `ERR_ITEM_INVALID_STATE` | 409 |
| `ERR_GUIDELINE_MISSING` | 422 |
| `ERR_HIGH_VALUE_NEEDS_MANAGER` | 422 |
| `ERR_NO_OPEN_CYCLE` | 409 |
| `ERR_TILL_SESSION_OPEN_EXISTS` | 409 |
| `ERR_TILL_INVALID_STATE` | 409 |
| `ERR_SALE_INVALID_STATE` | 409 |
| `ERR_SALE_VOID_WINDOW_CLOSED` | 422 |
| `ERR_ROUTE_INVALID_STATE` | 409 |
| `ERR_ROUTE_EMPTY` | 422 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 422 |
| `ERR_STOP_INVALID_STATE` | 409 |
| `ERR_STOP_OUT_OF_SEQUENCE` | 422 |
| `ERR_STOP_WINDOW_CONFLICT` | 422 |
| `ERR_DONOR_INACTIVE` | 422 |
| `ERR_DRIVER_NOT_STAFF` | 422 |
| `ERR_WORKER_NOT_ACTIVE` | 422 |
| `ERR_WORKER_CAP_REACHED` | 422 |
| `ERR_WEEKLY_HOURS_EXCEEDED` | 422 |
| `ERR_SHIFT_FULL` | 422 |
| `ERR_SHIFT_OVERLAP` | 422 |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 |
| `ERR_CYCLE_INVALID_STATE` | 409 |
| `ERR_TILL_SESSIONS_UNCLOSED` | 409 |
| `ERR_TRANSFER_INVALID_STATE` | 409 |
| `ERR_ALLOCATION_SUM_INVALID` | 422 |
| `ERR_SOD_APPROVER_IS_PREPARER` | 422 |
| `ERR_SOD_APPROVER_IS_COUNTER` | 422 |
| `ERR_RECEIPT_INVALID_STATE` | 409 |
| `ERR_RECEIPT_LOCKED` | 422 |
| `ERR_RECEIPT_NOT_REQUESTED` | 422 |
| `ERR_APPRAISAL_REQUIRED` | 422 |
| `ERR_DONOR_ADDRESS_REQUIRED` | 422 |
| `ERR_BALE_INVALID_STATE` | 409 |
| `ERR_BALE_UNDERWEIGHT` | 422 |
| `ERR_VENDOR_RATE_MISSING` | 422 |
