# Crating, Export Packing & ISPM-15 API — Product Requirements Document

## 1. Introduction

An industrial crating and export-packing operation lives or dies by three disciplines at once: engineering a crate that survives the voyage, proving to customs authorities that every piece of wood packaging is ISPM-15 heat-treated and stamped, and keeping the commercial paperwork — packing list against commercial invoice — internally consistent down to the kilogram and the cent. This document specifies an API that manages that full lifecycle for a crating company: capturing item dimensions and weights, engineering crate designs from those dimensions, reserving and consuming certified lumber from heat-treated batches, minting and voiding ISPM-15 stamp serials, declaring dangerous goods and batteries-in-equipment under segregation of duties, booking shop or on-site labor, planning container loads within payload and dangerous-goods segregation limits, releasing export documents, and settling post-delivery damage claims against declared values.

The system is deliberately conservative about money, wood, and stamps. Quotes exist in two variants — a live provisional quote used during negotiation and a final invoice computed from actual completed labor at job close — and customer credit exposure is tracked from quote acceptance until closure. Lumber is a pooled, quota-like resource: board feet are reserved at design approval, consumed at build time, partially scrapped when a sealed crate is reopened, and a batch that runs dry depletes itself automatically. Stamp serials are likewise a finite custody chain: every seal consumes one serial, every reopen voids one permanently. All endpoints are mounted under the `/crating` prefix, and all time-dependent rules (certificate expiry, claim windows, depreciation) are evaluated against a server-owned logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes eight roles, spelled exactly as follows: `Customer`, `SalesRep`, `CratingDesigner`, `ShopForeman`, `ComplianceOfficer`, `LogisticsCoordinator`, `ClaimsAdjuster`, and `PlatformAdmin`. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED`. Access to each operation is restricted by role; a caller whose role is not admitted by the endpoint is rejected with `ERR_FORBIDDEN`.

Role identity works in two ways. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`, so a customer accepting a quote, filing a damage claim, or appealing a denial must act on a job whose `customer_id` equals their own identifier, and a mismatch is rejected with `ERR_FORBIDDEN`. For every other role — `SalesRep`, `CratingDesigner`, `ShopForeman`, `ComplianceOfficer`, `LogisticsCoordinator`, `ClaimsAdjuster`, and `PlatformAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `prepared_by_user_id` or `approved_by_user_id` on a hazardous-goods declaration) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in this API — customers, packing jobs, items, crate designs, wood batches, crates, declarations, documents, crews, bookings, permits, containers, and claims alike — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-08-01T09:15:30.123Z`), recorded when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including modifications the server makes itself while recomputing derived fields or reconciling derived states.

This convention provides a consistent audit trail and unique addressability for every entity in the system, and the `version` field is the backbone of the optimistic-concurrency rules in §2.7.

### 2.5. The Logical Clock and Time-Governed Rules

The server maintains a logical clock that governs every time-dependent rule in the system. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A test-driving capability reserved for `PlatformAdmin` advances the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc` in its response.

Three rule families consume the logical clock. First, a wood batch's heat-treatment certificate expiry is evaluated lazily: any read or use of a batch whose `expires_at` is earlier than the current logical time flips the batch to `EXPIRED`, so advancing the clock re-evaluates expiry on the next batch read or use. Second, delivery stamps `delivered_at` from the logical clock, and the damage-claim filing window and the moisture-depreciation schedule both measure elapsed time from that stamp. Third, every claim records `filed_at` from the logical clock at the moment it is created.

### 2.6. Units, Precision, and Rounding Discipline

Money is counted in integer cents throughout the API: prices, costs, surcharges, declared values, claim amounts, and credit limits are all whole numbers of cents, and every monetary computation rounds half-up to a whole cent at each pinned step of its formula rather than only at the end. Where a rate is expressed in basis points — the invoice line's `duty_rate_bp` — the value lies between 0 and 10000 inclusive.

Physical quantities follow fixed precision rules. Volumes in cubic meters are carried to six decimal places. Dimensional weights, freight densities, tare weights, and booked hours are rounded half-up to two decimal places. Lumber quantities are whole board feet; whenever a computed lumber requirement lands between two integers it rounds up to the next whole board foot, so a design never under-reserves wood. Tiered lookups — lumber discounts, handling-fee percentages, freight classes — use inclusive floors: a value sitting exactly on a tier boundary qualifies for the better tier.

### 2.7. Optimistic Concurrency Control

Two write operations in the system require the caller to prove it has observed the current state of the parent entity before writing.

Creating a crate design for an item supersedes that item's existing non-terminal designs and is legitimate even when a prior design exists, but the request must carry `expected_item_version` equal to the item's current `version`. If the item's version has advanced since the caller last read it, the caller's view of the item's design set is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Revising a quoted job's terms is legitimate at any time while the job remains `QUOTED`, but the request must carry `expected_packing_job_version` equal to the job's current `version`. If the job's version no longer matches — for example because an item was captured after the caller's last read — the revision is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's view of the quote basis is stale.

No other endpoint accepts or requires a version field.

### 2.8. Path Resolution and the Validation Ladder

Requests that target nested resources are validated from the outside in. Path identifiers — the variables `id`, `itemId`, and `containerId`, rendered in §4 paths inside braces — are resolved left to right — the packing job before the item, the item before the design — and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve. Identifiers supplied in the request body must likewise resolve and must belong to the parent named in the path: `customer_id` on job creation, `wood_batch_id` on design approval, `design_id` on crate creation, `crew_id` on a labor booking, `crate_id` on load/unload operations and on claims, and the crate references inside document `lines` all resolve against the enclosing parent, failing which the request is rejected with `ERR_NOT_FOUND`.

Beyond resolution, every request walks a single validation ladder, and when a request would fail several checks the failure earliest in this ladder is the one reported. The tiers, in order:

1. **Authentication** — the identity headers of §2.1 are present and name a known role; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization** — the caller's role is admitted by the endpoint, and a `Customer`-role caller acts only on its own resources; otherwise `ERR_FORBIDDEN`.
3. **Request-body shape** — required fields present, types valid, enum members recognized, and ranges respected (dimensions and weights strictly positive, `end_at` later than `start_at`, line quantities at least one, claimed amounts strictly positive, `duty_rate_bp` between 0 and 10000 inclusive); otherwise `ERR_INVALID_REQUEST`.
4. **Existence** — the left-to-right path resolution and body-reference resolution described above; otherwise `ERR_NOT_FOUND`.
5. **Staleness** — the optimistic-concurrency checks of §2.7; otherwise `ERR_STALE_VERSION`.
6. **Lifecycle state guards** — the job-state guard `ERR_JOB_INVALID_STATE`, the customer-active guard `ERR_CUSTOMER_SUSPENDED`, and each entity's transition guard: `ERR_DESIGN_INVALID_STATE`, `ERR_CRATE_INVALID_STATE`, `ERR_DECLARATION_INVALID_STATE`, `ERR_DOC_INVALID_STATE`, `ERR_CONTAINER_INVALID_STATE`, `ERR_CLAIM_INVALID_STATE`, and the general `ERR_INVALID_STATE` for the booking, permit, batch, and customer lifecycles. The job-scoped cross-entity guards close out this tier: the approved-design guard and its permit sibling at packing start (`ERR_NO_APPROVED_DESIGN`, with `ERR_PERMIT_REQUIRED` sitting in the same tier), the released-documents guard `ERR_DOCS_NOT_RELEASED`, the open-claims guard `ERR_OPEN_CLAIMS`, and the item-capturability pair `ERR_ITEM_NOT_CAPTURABLE` / `ERR_ITEM_HAS_CRATE`.
7. **Business safety** — declaration presence at seal (`ERR_HAZMAT_DECLARATION_REQUIRED`), batch activity (`ERR_BATCH_NOT_ACTIVE`), dangerous-goods segregation in a container (`ERR_DG_SEGREGATION_VIOLATION`), protection-device fidelity at packing, crew qualification (`ERR_CREW_UNQUALIFIED`), and segregation of duties on declarations (`ERR_SOD_VIOLATION`). Within the packing check, the shock indicator is compared before the moisture barrier, so a crate failing both surfaces `ERR_INDICATOR_MISMATCH` rather than `ERR_BARRIER_MISMATCH`.
8. **Temporal** — the claim filing window (`ERR_CLAIM_WINDOW_EXPIRED`).
9. **Resource constraints** — crew double-booking (`ERR_CREW_DOUBLE_BOOKED`), buffered permit-window conflict (`ERR_PERMIT_WINDOW_CONFLICT`), and the uniqueness invariants of §2.9 (`ERR_DUPLICATE`).
10. **Cross-document referential consistency** — the release-time checks of §3.7 in their pinned sub-order: `ERR_DOC_CRATE_MISMATCH` first, then `ERR_DOC_QUANTITY_MISMATCH`, then `ERR_DOC_WEIGHT_MISMATCH`, then `ERR_INVOICE_UNDERVALUED`; the crate-creation design check (`ERR_NO_APPROVED_DESIGN`) also lives in this tier.
11. **Fiscal ceilings** — credit exposure (`ERR_CREDIT_LIMIT_EXCEEDED`), lumber sufficiency (`ERR_INSUFFICIENT_WOOD`), stamp availability (`ERR_STAMPS_EXHAUSTED`), and container payload (`ERR_CONTAINER_OVERWEIGHT`).

### 2.9. Uniqueness Invariants

A small set of uniqueness rules protects the custody chain and the paper trail, each enforced at creation time and each rejected with `ERR_DUPLICATE` (HTTP 409). A customer's `site_code` is unique across all customers, because it doubles as the resource key for on-site permit overlap checks. A wood batch's `ht_certificate_no` is unique, since it identifies one ISPM-15 heat-treatment certificate. A container's `container_no` is unique. A packing job carries at most one packing list and at most one commercial invoice; a second create for either document on the same job is a duplicate. Finally, an item has at most one crate that is not `VOIDED`.

### 2.10. Segregation of Duties

Two compliance workflows deliberately split authority across roles. A hazardous-goods declaration is prepared by one operator and judged by another: the approving or rejecting `ComplianceOfficer` must carry an `X-User-ID` different from the declaration's `prepared_by_user_id`, and a same-operator attempt is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Export documents follow a similar split: a `SalesRep` drafts and finalizes the packing list and commercial invoice, but only a `ComplianceOfficer` may release them, keeping the person who wrote the numbers from being the person who certifies them.

### 2.11. Derived Status and Cross-Entity Cascades

Several statuses in this system are derived rather than directly set, and the server transitions resources automatically when their criteria are met or broken — no client request on that specific resource is required. A packing job's progress through `READY_TO_LOAD` and `LOADED` is a compound readout of its crates' states, and its `readiness_posture` recomputes whenever a crate changes state or a compliance hold lands. An item's status bubbles up from its design and crate events. A wood batch depletes and recovers on its own as lumber is reserved, consumed, and released, and expires lazily against the logical clock. Cancellation of a job is the largest cascade: it supersedes designs, releases wood reservations, voids crates, cancels bookings and permits, and re-derives batch status in one motion. The per-workflow details — including which transitions bump the job's `version` — are given in §3.

## 3. Business Logic & Workflows

### 3.1. Customer Intake, Item Capture, and Quoting

Every engagement begins with the account. A `SalesRep` registers a customer by supplying the legal `name`, a `site_code` that identifies the customer's premises (and later anchors on-site permit overlap checks), and a `credit_limit_cents` ceiling on open exposure, which must not be negative. A new customer starts `ACTIVE` with an `open_exposure_cents` of zero. That exposure is a running total: it sums the `quoted_price_cents` of every one of the customer's jobs in `DESIGN`, `PACKING`, `READY_TO_LOAD`, `LOADED`, `SHIPPED`, or `DELIVERED` status — jobs still `QUOTED` have not been accepted, and jobs `CLOSED` or `CANCELLED` have released their exposure. A `SalesRep` may later update the `name` or `credit_limit_cents`, which bumps the customer's `version`, and may suspend an `ACTIVE` customer or reinstate a `SUSPENDED` one; any other lifecycle combination is rejected with `ERR_INVALID_STATE`. A suspended customer cannot take on new work: creating a job for a `SUSPENDED` customer, or accepting a quote under one, is rejected with `ERR_CUSTOMER_SUSPENDED`.

With an account in place, a `SalesRep` opens a packing job by naming the owning `customer_id`, the `mode` — `SHOP` when packing happens in the crating shop, `ONSITE` when a crew travels to the customer — and the `incoterm` (`EXW`, `FOB`, or `DDP`). The job is born `QUOTED` with its `readiness_posture` at `BLOCKED`, its totals (`total_board_feet`, `total_chargeable_weight_kg`, `estimated_labor_hours`, `quoted_price_cents`) at zero, `invoiced_total_cents` null, and `delivered_at` null. A job walks the status line `QUOTED` → `DESIGN` → `PACKING` → `READY_TO_LOAD` → `LOADED` → `SHIPPED` → `DELIVERED` → `CLOSED`, with `CANCELLED` reachable only from `QUOTED` or `DESIGN`; the middle two statuses are largely automatic, as §3.4 and §3.8 describe.

While the job is `QUOTED`, the `SalesRep` captures the cargo. Each item takes a free-text `description`; strictly positive `length_cm`, `width_cm`, and `height_cm`; a strictly positive actual `weight_kg`; a `fragile_class` of `STANDARD`, `DELICATE`, or `HIGHLY_FRAGILE`; and a non-negative `declared_value_cents` for customs and claims purposes. Two optional flags complete the capture: `hazmat` (default false) marks dangerous goods, and `battery_in_equipment` (default `NONE`, otherwise `LITHIUM_ION`, `LITHIUM_METAL`, or `WET_CELL`) marks a battery shipped inside equipment. From these inputs the server computes `volume_m3` — the product of the three dimensions divided by one million, carried to six decimal places — then `dimensional_weight_kg`, the same product divided by five thousand and rounded half-up to two decimals, and finally `chargeable_weight_kg`, the greater of the actual weight and the dimensional weight. Any values a client sends for server-computed fields such as `dimensional_weight_kg` or `chargeable_weight_kg` are ignored. Capturing an item bumps the parent job's `version`, and the item itself starts in `CAPTURED` status. Attempting to capture an item after the job has left `QUOTED` is rejected with `ERR_JOB_INVALID_STATE`.

Corrections are possible but only while nothing downstream depends on the numbers. An item may be re-measured — any of `description`, `length_cm`, `width_cm`, `height_cm`, `weight_kg`, `fragile_class`, `hazmat`, `battery_in_equipment`, or `declared_value_cents` may be revised — only while the job is still `QUOTED` (otherwise `ERR_JOB_INVALID_STATE`) and only while the item has no design in any status other than `SUPERSEDED`; once a live design exists the attempt is rejected with `ERR_ITEM_NOT_CAPTURABLE`. A successful correction recomputes the volume and both weight figures and bumps both the item's `version` and the parent job's `version`. Similarly, the job's `mode` and `incoterm` may be revised while `QUOTED`, subject to the optimistic-concurrency rule of §2.7, and each such revision recomputes the live quote.

Three aggregates summarize the job at all times. `total_board_feet` sums the `board_feet_required` of every item's current design — designs in `SUPERSEDED` do not count. `total_chargeable_weight_kg` sums `chargeable_weight_kg` over all items. `estimated_labor_hours` takes the total item volume in cubic meters, multiplies by the mode's hours-per-cubic-meter rate (one and a half for `SHOP`, two and a half for `ONSITE`), and rounds up to the next whole hour.

The provisional quote is a computed read with a pinned evaluation order: line components first, then the subtotal, then the handling fee keyed on that subtotal, then the fuel surcharge, then the total. The wood component multiplies the job's `total_board_feet` by 350 cents per board foot, then applies a volume discount to the whole wood cost — ten percent when the job consumes at least 500 board feet, five percent when it consumes at least 200, nothing below that — rounding the discounted figure half-up to whole cents. The labor component multiplies `estimated_labor_hours` by the mode's hourly rate (8500 cents for `SHOP`, 12000 cents for `ONSITE`) and adds a flat travel charge of 15000 cents for `ONSITE` jobs only. The protection component sums, over every item, the shock-indicator cost for the design's required rating (900 cents for a 75G indicator, 1200 for 50G, 1800 for 25G) plus the moisture-barrier cost (0 for `NONE`, 2500 cents for `VCI`, 6000 cents for `VACUUM_SEALED`). The hazardous surcharge adds 4500 cents for every item flagged `hazmat` or carrying a `battery_in_equipment` other than `NONE`. An item with no current design still contributes its volume to the labor estimate but contributes nothing to the wood and protection lines. The subtotal is the sum of the wood, labor, protection, and hazmat components. The handling fee is three percent of the subtotal when the subtotal reaches 2000000 cents, five percent when it reaches 500000 cents, and eight percent otherwise, rounded half-up to whole cents. The fuel surcharge is nine percent of the subtotal plus handling, again rounded half-up. The quote total is subtotal plus handling plus fuel. The breakdown is returned with field names `quoted_price_cents`, `subtotal_cents`, `wood_cost_cents`, `labor_cost_cents`, `protection_cost_cents`, `hazmat_cost_cents`, `handling_fee_cents`, and `fuel_surcharge_cents`, alongside `estimated_labor_hours`, `total_chargeable_weight_kg`, and `total_board_feet`.

Acceptance belongs to the customer. When the acting customer's `X-User-ID` matches the job's `customer_id` (otherwise `ERR_FORBIDDEN`), and the customer is `ACTIVE` (otherwise `ERR_CUSTOMER_SUSPENDED`), and adding this job's quoted price to `open_exposure_cents` would not exceed `credit_limit_cents` (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`), the customer may accept the quote. Acceptance freezes `quoted_price_cents` as a snapshot of the provisional quote at that instant, adds it to the customer's `open_exposure_cents`, moves the job from `QUOTED` to `DESIGN`, and bumps the job's `version`.

### 3.2. Crate Design, Geometry, and Wood Reservation

A `CratingDesigner` authors crate designs against a captured item. Creating a design carries the optimistic-concurrency field `expected_item_version` described in §2.7, and it is the supersede mechanism: any of the item's existing designs in `DRAFT`, `IN_REVIEW`, or `REJECTED` are moved to `SUPERSEDED` by the act of creation, and the new design's `revision` is the count of the item's prior designs plus one — so the first design bears `revision` 1. Creation is refused outright, with `ERR_ITEM_HAS_CRATE`, when the item already has a crate that is not `VOIDED`. A new design starts in `DRAFT` with `wood_batch_id` and `reject_reason` null, and its creation bumps the item's `version`.

A design's geometry is computed from the item's current measurements at creation, and again whenever a rejected design is revised. Clearance is driven by fragility: `clearance_cm` is 5 centimeters for `STANDARD`, 10 for `DELICATE`, and 15 for `HIGHLY_FRAGILE`. Each internal dimension is the item dimension plus twice the clearance on that axis, yielding `internal_l_cm`, `internal_w_cm`, and `internal_h_cm`. Board thickness follows the item's actual weight: `thickness_cm` is 1.2 centimeters below 50 kilograms, 1.8 centimeters from 50 up to but not including 500 kilograms, and 2.5 centimeters at 500 kilograms or more. Each external dimension — `external_l_cm`, `external_w_cm`, `external_h_cm` — is the internal dimension plus twice the thickness. The lumber requirement, `board_feet_required`, doubles the sum of the three external face products (length times width, plus length times height, plus width times height, in square centimeters), converts the result to square meters by dividing by ten thousand, multiplies by eleven board feet per square meter, and rounds up to a whole board foot. The crate's own weight, `tare_weight_kg`, is the board footage multiplied by 1.8 kilograms per board foot, rounded half-up to two decimals. Protection requirements are pinned on the design as well: `shock_indicator_g` is 75 for `STANDARD`, 50 for `DELICATE`, and 25 for `HIGHLY_FRAGILE`; and `moisture_barrier_required` is `VACUUM_SEALED` whenever the item's `battery_in_equipment` is anything other than `NONE`, otherwise `VCI` whenever the item's `fragile_class` is anything other than `STANDARD`, otherwise `NONE`.

Review flows through the compliance desk. The designer submits a `DRAFT` design, moving it to `IN_REVIEW`. A `ComplianceOfficer` then approves or rejects it; attempts from any other source state are rejected with `ERR_DESIGN_INVALID_STATE`. Approval takes a `wood_batch_id` in the payload and runs two fiscal-physical checks: the referenced batch must be `ACTIVE` and not past its `expires_at` against the logical clock (otherwise `ERR_BATCH_NOT_ACTIVE`), and its `available_board_feet` must be at least the design's `board_feet_required` (otherwise `ERR_INSUFFICIENT_WOOD`). On approval the design pins that `wood_batch_id`, the batch's `reserved_board_feet` increases by the required footage, `available_board_feet` is recomputed — and if availability has fallen to zero while reserved plus consumed footage is positive, the batch flips itself to `DEPLETED` — and the item bubbles from `CAPTURED` to `DESIGN_APPROVED`. Rejection records the payload's `reason` into the design's `reject_reason` and leaves the design `REJECTED`. The designer may revise a `REJECTED` design, returning it to `DRAFT` with `revision` incremented by one and all geometry recomputed from the item's current dimensions.

Designs reach `SUPERSEDED` in two ways. Supersede-by-create — the creation flow above — applies to designs in `DRAFT`, `IN_REVIEW`, or `REJECTED`. The job-cancellation cascade of §3.9 additionally supersedes designs in `APPROVED` or `LOCKED`, and those two releases return their reserved lumber: the batch's `reserved_board_feet` decreases by `board_feet_required`. Once a crate is created against an `APPROVED` design, the design moves to `LOCKED` and becomes immutable thereafter — the crate has pinned the design, and supersede-by-create is no longer possible for it.

### 3.3. Certified Lumber: Wood Batches and ISPM-15 Stamp Custody

Lumber enters the system as certified batches. A `ComplianceOfficer` registers a wood batch with its ISPM-15 heat-treatment certificate number `ht_certificate_no`, a `treatment_type` of `HT` or `KD_HT`, the certificate's `expires_at`, the strictly positive `received_board_feet` of lumber delivered, and the non-negative count `stamps_acquired` of physical stamp serials issued against the batch. A fresh batch is `ACTIVE` with all movement counters at zero.

Each batch keeps a lumber ledger and a stamp ledger. On the lumber side, `reserved_board_feet` accrues at design approval and is released at supersede or cancellation; `consumed_board_feet` accrues when a crate is built and the wood is actually cut; `scrapped_board_feet` accrues when a sealed crate is reopened, sacrificing two board feet of padding per reopen; and `available_board_feet` is always the received footage minus the reserved, consumed, and scrapped amounts. On the stamp side, `stamps_applied` counts serials currently active on sealed crates, `stamps_voided` counts serials voided by reopens — a voided serial is never reusable — and `stamps_available` is the acquired count minus applied minus voided.

Batch status is partly automatic. When `available_board_feet` reaches zero while the sum of reserved and consumed footage is positive, the batch moves itself from `ACTIVE` to `DEPLETED`; when a later reservation release pushes availability above zero again, it recovers from `DEPLETED` back to `ACTIVE` on its own. Expiry is lazy and terminal: any read or use of an `ACTIVE` or `SUSPENDED` batch whose `expires_at` lies before the current logical clock moves it to `EXPIRED`, from which there is no return.

A `ComplianceOfficer` may also suspend an `ACTIVE` batch — the compliance red flag — and later reinstate a `SUSPENDED` one, provided the certificate has not expired against the logical clock (otherwise `ERR_BATCH_NOT_ACTIVE`); other lifecycle combinations are rejected with `ERR_INVALID_STATE`. Suspension cascades immediately: every crate whose pinned design draws on this batch and which currently sits in `PLANNED`, `BUILT`, `PACKED`, or `SEALED` has its `compliance_hold` set true, and each affected job's `readiness_posture` is recomputed — a job reading `READY` drops to `BLOCKED`. Reinstatement clears `compliance_hold` on all crates whose pinned design uses the batch and recomputes the affected postures again. A crate under a compliance hold fails the batch-activity guard at build, seal, and container load with `ERR_BATCH_NOT_ACTIVE`, which is the intended serialization point between batch discipline and floor operations.

### 3.4. Shop Floor Operations: Build, Pack, Seal, Reopen

Physical work begins when a `ShopForeman` starts packing on a job in `DESIGN`. Two cross-entity guards apply, in the same validation tier: at least one item must exist and every item must hold a design in `APPROVED` or `LOCKED` status (otherwise `ERR_NO_APPROVED_DESIGN`), and an `ONSITE` job must hold an on-site permit in `CONFIRMED` status (otherwise `ERR_PERMIT_REQUIRED`). Starting packing moves the job to `PACKING` and bumps its `version`.

Crates come into existence against approved engineering. A `ShopForeman` creates a crate by supplying a `design_id`; the design must belong to this item and be `APPROVED` (otherwise `ERR_NO_APPROVED_DESIGN`), and the item must not already have a crate that is not `VOIDED` (otherwise `ERR_DUPLICATE`). Creation pins the design — the design moves from `APPROVED` to `LOCKED` and the crate's `design_id` is immutable thereafter — and the crate is born `PLANNED` with `container_id`, `stamp_serial`, and `stamp_status` null and `compliance_hold` false. The crate records its `item_id` from the path and a denormalized `packing_job_id` for query convenience. Its physical identity is computed once at creation from the pinned design: `tare_weight_kg` copied from the design, `gross_weight_kg` equal to the item's `weight_kg` plus the tare, `external_volume_m3` as the product of the design's three external dimensions divided by one million and carried to six decimals, and `freight_density_kg_m3` as the gross weight divided by that volume, rounded half-up to two decimals. From density comes the NMFC `freight_class`, the first tier whose inclusive floor the density meets: at least 800 kilograms per cubic meter earns class `55`; at least 400 earns `60`; at least 200 earns `65`; at least 100 earns `70`; at least 50 earns `77.5`; at least 25 earns `85`; at least 10 earns `92.5`; anything lighter earns `125`. From here a crate walks `PLANNED` → `BUILT` → `PACKED` → `SEALED` → `LOADED` → `SHIPPED` → `DELIVERED`, with a `REOPENED` detour and a `VOIDED` terminus described below; transition attempts from the wrong source state are rejected with `ERR_CRATE_INVALID_STATE`.

Building turns reservations into cut wood. A `PLANNED` crate is built only while its job is `PACKING` (otherwise `ERR_JOB_INVALID_STATE`), only while the pinned design's batch is `ACTIVE` and unexpired against the logical clock, and only while the crate carries no compliance hold (both batch failures surface as `ERR_BATCH_NOT_ACTIVE`). A successful build moves the crate to `BUILT` and converts the batch's reservation into consumption: `reserved_board_feet` decreases by the design's `board_feet_required` while `consumed_board_feet` increases by the same amount.

Packing fits the item and its protection devices. From `BUILT` — or from `REOPENED`, the detour described below — a `ShopForeman` packs the crate by declaring the installed protection: the payload's `indicator_g` must equal the pinned design's `shock_indicator_g` (otherwise `ERR_INDICATOR_MISMATCH`), and the payload's `moisture_barrier` must equal the design's `moisture_barrier_required` (otherwise `ERR_BARRIER_MISMATCH`); when both are wrong, the indicator error surfaces first. Packing from `BUILT` bubbles the item to `PACKED`; packing from `REOPENED` leaves the item where the reopen put it.

Sealing is the compliance act. A `ComplianceOfficer` seals a `PACKED` crate while the job is `PACKING` or `READY_TO_LOAD` (otherwise `ERR_JOB_INVALID_STATE`). Three guards protect the seal. The dangerous-goods guard: if the item's `hazmat` is true or its `battery_in_equipment` is anything other than `NONE`, an `APPROVED` hazardous-goods declaration must exist for the item (otherwise `ERR_HAZMAT_DECLARATION_REQUIRED`). The batch guard: the pinned design's batch must be `ACTIVE` and unexpired, and the crate must carry no compliance hold (otherwise `ERR_BATCH_NOT_ACTIVE`). The stamp guard: the batch's `stamps_available` must be greater than zero (otherwise `ERR_STAMPS_EXHAUSTED`). A successful seal mints the crate's `stamp_serial` — the literal prefix `ISPM15-`, then the batch's `ht_certificate_no`, then a hyphen, then a four-digit zero-padded sequence equal to the batch's `stamps_applied` plus `stamps_voided` plus one — sets `stamp_status` to `ACTIVE`, increments the batch's `stamps_applied` by one, bubbles the item to `SEALED`, and triggers the job's readiness auto-check described below.

Reopening is the costly undo. A `ShopForeman` may reopen a `SEALED` crate, moving it to `REOPENED`. The stamp is destroyed as an instrument but kept as evidence: `stamp_status` becomes `VOIDED` while the `stamp_serial` string is retained for audit, the batch's `stamps_applied` decreases by one and its `stamps_voided` increases by one, and two board feet of padding are sacrificed — `consumed_board_feet` decreases by two while `scrapped_board_feet` increases by two. The item falls back from `SEALED` to `PACKED`, and if the job had advanced to `READY_TO_LOAD` it reverts to `PACKING`.

Readiness is a compound readout of the floor. A job's `readiness_posture` reads `READY` exactly when at least one crate exists, every crate sits in `SEALED`, `LOADED`, `SHIPPED`, or `DELIVERED`, and no crate carries a compliance hold; in every other situation it reads `BLOCKED`. When the sealed-set condition first becomes true the job moves itself from `PACKING` to `READY_TO_LOAD`; when any crate leaves that set — a reopen being the canonical cause — it falls back to `PACKING`. Loading and unloading, covered in §3.8, drive the companion pair: the job advances from `READY_TO_LOAD` to `LOADED` once every crate is `LOADED`, `SHIPPED`, or `DELIVERED`, and slips back to `READY_TO_LOAD` if a crate is unloaded.

### 3.5. Dangerous Goods Declarations

Any item flagged `hazmat`, and any item whose `battery_in_equipment` is not `NONE`, must carry an `APPROVED` declaration before its crate can be sealed. A `ShopForeman` or `ComplianceOfficer` drafts the declaration against the item with its `un_number` (for example, UN3481), a `dg_class` of `1`, `2.1`, `3`, `4.1`, `5.1`, `6.1`, `8`, or `9`, a `packing_group` of `I`, `II`, or `III`, and an optional `battery_type` — `NONE`, `LITHIUM_ION`, `LITHIUM_METAL`, or `WET_CELL`, defaulting to `NONE` — mirroring the item's battery flag. The server records the creator's `X-User-ID` as `prepared_by_user_id`, starts the declaration in `DRAFT` at `revision` 1, and leaves `approved_by_user_id` null.

The declaration walks `DRAFT` → `SUBMITTED` → `APPROVED` or `REJECTED`, with a cyclic return from `REJECTED` to `DRAFT`; transitions from the wrong state are rejected with `ERR_DECLARATION_INVALID_STATE`. Submission is performed by a `ShopForeman` or `ComplianceOfficer`. Judgment belongs to a `ComplianceOfficer` alone, under segregation of duties: whether approving or rejecting, the officer's `X-User-ID` must differ from the declaration's `prepared_by_user_id`, and a same-operator judgment is rejected with `ERR_SOD_VIOLATION`. Approval additionally stamps `approved_by_user_id` with the officer's identifier. Revision returns a `REJECTED` declaration to `DRAFT`, increments its `revision` by one, and resets `approved_by_user_id` to null, ready for a fresh round.

### 3.6. Crews, Labor Bookings, and On-Site Permits

Crews are the capacity pool. A `ShopForeman` registers a crew with a `name` and a non-empty `capabilities` list drawn from `SHOP_BUILD`, `ONSITE_PACK`, and `HAZMAT_CERT`; a crew is `ACTIVE` when created and may read as `INACTIVE` thereafter.

Booking crew time against a job requires the job to have been accepted — a booking attempt while the job is still `QUOTED` is rejected with `ERR_JOB_INVALID_STATE`. The `ShopForeman` supplies the `crew_id`, a `mode` that must equal the job's own `mode`, and a half-open interval: `start_at` is inclusive, `end_at` is exclusive and must be later than `start_at`. Qualification is enforced at booking: the crew must hold the capability matching the mode — `SHOP_BUILD` for a `SHOP` job, `ONSITE_PACK` for an `ONSITE` job — and must additionally hold `HAZMAT_CERT` whenever the job contains any item flagged `hazmat` or carrying a battery (otherwise `ERR_CREW_UNQUALIFIED`). Overlap is enforced on the crew, not the job: the new half-open interval must not overlap any existing `RESERVED` or `CONFIRMED` booking of the same crew, though two bookings may touch back-to-back — one ending exactly when the next begins is adjacency, not overlap — and a genuine overlap is rejected with `ERR_CREW_DOUBLE_BOOKED`. Each booking computes its own economics: `hours` is the interval's duration in seconds divided by 3600 and rounded to two decimals; `rate_cents_per_hour` is 8500 for `SHOP` work and 12000 for `ONSITE`; `travel_surcharge_cents` is a flat 15000 per `ONSITE` booking and zero for `SHOP`; and `total_cost_cents` is the hours-times-rate figure rounded half-up to whole cents plus the travel surcharge. A booking is born `RESERVED`, is confirmed to `CONFIRMED`, completed to `COMPLETED`, and may be cancelled from `RESERVED` or `CONFIRMED`; any other lifecycle step is rejected with `ERR_INVALID_STATE`. Completed bookings are what the final invoice consumes at job close, per §3.9.

On-site work additionally requires a permit for the customer's premises. A `LogisticsCoordinator` requests a permit with an inclusive `window_start` and an inclusive `window_end` that must be later than the start; the server copies the `site_code` from the job's customer at creation, and the permit begins as `REQUESTED`. Permits contend on the site, not the job: the requested closed window, extended by a sixty-minute buffer on both sides, must not intersect the correspondingly buffered window of any other `REQUESTED` or `CONFIRMED` permit bearing the same `site_code` — touching within the buffer still counts as a conflict — and a violation is rejected with `ERR_PERMIT_WINDOW_CONFLICT`. A `LogisticsCoordinator` confirms a `REQUESTED` permit to `CONFIRMED`; other lifecycle steps are rejected with `ERR_INVALID_STATE`. The permit then rides the job's fate: a permit still `CONFIRMED` when its job closes moves to `CLOSED`, while permits in `REQUESTED` or `CONFIRMED` when the job is cancelled move to `CANCELLED`. Recall from §3.4 that an `ONSITE` job cannot start packing without a `CONFIRMED` permit.

### 3.7. Export Documents: Packing List and Commercial Invoice

Two documents travel with every export job, each existing at most once per job (a second create is rejected with `ERR_DUPLICATE`), and each upserted — created or replaced in full — only while the document itself is `DRAFT` or `AMENDING` and the job sits anywhere from `DESIGN` through `LOADED` inclusive; an upsert outside those conditions is rejected with `ERR_DOC_INVALID_STATE` or, where the job itself is out of range, `ERR_JOB_INVALID_STATE`.

A `SalesRep` maintains the packing list as a set of `lines`, each naming a `crate_id` that must belong to this job, a `description`, an integer `qty` of at least one, and strictly positive `net_weight_kg` and `gross_weight_kg` figures. The document's `total_gross_weight_kg` is the sum of its lines' gross weights, kept to two decimal places. The commercial invoice is likewise a set of `lines`, each with a `crate_id` belonging to the job, a `description`, an integer `qty` of at least one, a non-negative `unit_price_cents`, and a `duty_rate_bp` between 0 and 10000. Its totals pin the rounding order line by line: `invoice_total_cents` sums, over all lines, each line's quantity multiplied by its unit price and rounded half-up to whole cents — rounding each line first and summing second, never the reverse — and `duty_total_cents` sums, over all lines, each rounded line total multiplied by its `duty_rate_bp`, divided by 10000, and rounded half-up to whole cents. Both documents are born `DRAFT`.

Finalization and release are deliberately split across roles, per §2.10. A `SalesRep` finalizes: both documents must exist and sit in `DRAFT` or `AMENDING` (otherwise `ERR_DOC_INVALID_STATE`), and the single call moves the packing list and the commercial invoice to `FINALIZED` together. A `ComplianceOfficer` releases: both documents must be `FINALIZED` (otherwise `ERR_DOC_INVALID_STATE`), and four consistency checks then run in a pinned order. First, the set of crate identifiers in the packing list's lines must equal the set in the invoice's lines (otherwise `ERR_DOC_CRATE_MISMATCH`). Second, crate by crate, the quantity on the packing list must equal the quantity on the invoice (otherwise `ERR_DOC_QUANTITY_MISMATCH`). Third, the packing list's `total_gross_weight_kg` must lie within half a kilogram of the sum of the crates' `gross_weight_kg` (otherwise `ERR_DOC_WEIGHT_MISMATCH`). Fourth, the invoice's `invoice_total_cents` must reach at least ninety-five percent of the sum of the job's items' `declared_value_cents` (otherwise `ERR_INVOICE_UNDERVALUED`). When all four pass, both documents move to `RELEASED` in the same call.

Corrections after release are possible only while the cargo has not left. A `SalesRep` may amend while the job is `READY_TO_LOAD` or `LOADED`; once the job is `SHIPPED` the attempt is rejected with `ERR_JOB_INVALID_STATE`. Amending moves both documents from `RELEASED` to `AMENDING` together, and the cycle — `AMENDING` to `FINALIZED` to `RELEASED` — may repeat as needed.

### 3.8. Container Load Planning, Shipping, and Delivery

Containers are the shipping capacity. A `LogisticsCoordinator` registers one with a unique `container_no`, a `size` of `20FT`, `40FT`, or `40HC`, and an optional non-negative `dunnage_weight_kg` — blocking and bracing material that counts against payload — defaulting to zero. The size pins the `max_payload_kg`: 21770 kilograms for a `20FT`, 26780 for a `40FT`, and 26680 for a `40HC`. The container's `payload_used_kg` is computed as the sum of the `gross_weight_kg` of the crates currently assigned to it in `LOADED` status, and a new container starts in `PLANNING`.

Loading is governed by four guards. The crate being loaded must be `SEALED` (other states fall to the crate transition guard, `ERR_CRATE_INVALID_STATE`), and the container must be `PLANNING` (otherwise `ERR_CONTAINER_INVALID_STATE`); a crate under a compliance hold is rejected with `ERR_BATCH_NOT_ACTIVE`. The weight guard adds the container's current `payload_used_kg`, its `dunnage_weight_kg`, and the candidate crate's `gross_weight_kg`, and requires the sum to be no more than `max_payload_kg` — exactly at the limit is admissible — otherwise the load is rejected with `ERR_CONTAINER_OVERWEIGHT`. The segregation guard reads the dangerous-goods declarations behind the crates: a crate whose item holds an `APPROVED` declaration of `dg_class` `1` may not share a container with any other crate carrying a dangerous-goods declaration of any class, and classes `3` and `5.1` may never be loaded into the same container; violations are rejected with `ERR_DG_SEGREGATION_VIOLATION`. A successful load sets the crate's `container_id`, adds the crate's gross weight to `payload_used_kg`, moves the crate from `SEALED` to `LOADED`, and triggers the job's auto-check: once every crate of the job is `LOADED`, `SHIPPED`, or `DELIVERED`, the job advances from `READY_TO_LOAD` to `LOADED`.

Unloading is the mirror, available only while the container is `PLANNING` (otherwise `ERR_CONTAINER_INVALID_STATE`): the crate must currently be `LOADED`, its `container_id` is cleared, its gross weight leaves `payload_used_kg`, the crate returns to `SEALED`, and a job that had reached `LOADED` reverts to `READY_TO_LOAD`.

A container is locked for departure by a `LogisticsCoordinator` — permitted only when at least one `LOADED` crate sits in it (otherwise `ERR_CONTAINER_INVALID_STATE`) — moving it from `PLANNING` to `LOCKED`. Unlocking returns a `LOCKED` container to `PLANNING` only when its `payload_used_kg` is zero, and gating out moves a `LOCKED` container to its terminal `GATED_OUT`.

Departure is a paperwork-gated transition. A `LogisticsCoordinator` ships a job that has reached `LOADED`: both the packing list and the commercial invoice must be `RELEASED` (otherwise `ERR_DOCS_NOT_RELEASED`), and every container holding this job's crates must be `GATED_OUT` (otherwise `ERR_CONTAINER_INVALID_STATE`). Shipping moves every `LOADED` crate to `SHIPPED`, the job to `SHIPPED`, and bumps the job's `version`. Delivery, likewise by a `LogisticsCoordinator`, moves the job from `SHIPPED` to `DELIVERED`, moves every `SHIPPED` crate to `DELIVERED`, stamps `delivered_at` from the logical clock — the timestamp from which the claim window and moisture depreciation of §3.9 are measured — and bumps the job's `version`.

### 3.9. Damage Claims and Job Closure

Once a job is `DELIVERED`, its customer may file damage claims; filing against a job in any earlier state is rejected with `ERR_JOB_INVALID_STATE`. Filing names a `crate_id` belonging to this job, a `claim_type` of `IMPACT`, `TILT`, `MOISTURE`, or `OTHER`, a free-text `description`, and a strictly positive `amount_claimed_cents`. Two identity rules apply: the caller's `X-User-ID` must equal the job's `customer_id` (otherwise `ERR_FORBIDDEN`), and the logical clock at filing must be no more than thirty days after the job's `delivered_at` (otherwise `ERR_CLAIM_WINDOW_EXPIRED`). A filed claim stamps `filed_at` from the logical clock and begins in `FILED`.

A `ClaimsAdjuster` picks the claim up, moving it from `FILED` to `UNDER_REVIEW`, and from there either denies it to `DENIED` or approves it to `APPROVED`; any transition from the wrong state — including a second appeal, below — is rejected with `ERR_CLAIM_INVALID_STATE`. Approval computes `amount_approved_cents` as the lesser of the claimed amount and a cap that depends on the claim variant. For `IMPACT` and `TILT` claims the cap is the full `declared_value_cents` of the damaged crate's item. For a `MOISTURE` claim the cap depreciates: the elapsed time from `delivered_at` to `filed_at` is reduced to whole days and then to whole weeks, the cap is the declared value multiplied by the larger of one half and one percent off per whole week — that is, the declared value scaled by one minus one hundredth per whole week since delivery, never falling below half — rounded half-up to whole cents. For an `OTHER` claim the cap is a flat half of the declared value, rounded half-up. The same claimed amount therefore yields a lower approved figure under `MOISTURE` than under `IMPACT` or `TILT` once a full week has passed, and `OTHER` always halves it.

A denied customer gets exactly one second chance. Appeal — moving the claim from `DENIED` back to `UNDER_REVIEW` — is available only to the customer whose `X-User-ID` matches the job's `customer_id` (otherwise `ERR_FORBIDDEN`) and only while `appeal_used` is false; the appeal sets `appeal_used` true, and a second appeal attempt is rejected with `ERR_CLAIM_INVALID_STATE`.

Settlement closes the loop. A `ClaimsAdjuster` settles an `APPROVED` claim by paying `amount_paid_cents`, which must lie between zero and `amount_approved_cents` inclusive (otherwise `ERR_INVALID_REQUEST`). The payment splits the approved amount: `amount_settled_cents` records what was paid and `amount_waived_cents` records the remainder, so that the approved amount always equals the settled plus the waived portions. Settlement moves the claim to its terminal `SETTLED`.

Closing the job is the fiscal finale, performed by a `SalesRep` on a `DELIVERED` job with no claim outstanding in `FILED`, `UNDER_REVIEW`, or `APPROVED` status (otherwise `ERR_OPEN_CLAIMS`; `DENIED` and `SETTLED` claims do not block). Closing computes the final invoice: `invoiced_total_cents` — null until this moment — takes the FINAL variant of the quote formula of §3.1, identical in structure except that the labor component is the sum of `total_cost_cents` over the job's `COMPLETED` labor bookings, actual hours at actual rates with each booking's travel surcharge, rather than the volume-derived estimate; the same cargo therefore produces a different total whenever actual hours diverge from the estimate. Closing also releases the customer's exposure — `open_exposure_cents` decreases by the frozen `quoted_price_cents` — moves the job to `CLOSED`, and bumps its `version`.

Cancellation is the early exit, available to a `SalesRep` only while the job is `QUOTED` or `DESIGN` (otherwise `ERR_JOB_INVALID_STATE`), and it unwinds everything the job touched. Every design in `DRAFT`, `IN_REVIEW`, `REJECTED`, `APPROVED`, or `LOCKED` moves to `SUPERSEDED`, and the `APPROVED` and `LOCKED` ones return their lumber: each batch's `reserved_board_feet` decreases by the corresponding `board_feet_required`. Every crate in `PLANNED`, `BUILT`, or `PACKED` moves to `VOIDED` — wood already consumed on a built crate is not returned, because it has already been cut. Every labor booking in `RESERVED` or `CONFIRMED` moves to `CANCELLED`, and every permit in `REQUESTED` or `CONFIRMED` moves to `CANCELLED`. Each affected batch then re-derives its own status — a `DEPLETED` batch whose availability has risen above zero returns to `ACTIVE`. Cancelling from `DESIGN` additionally releases the customer's exposure, decreasing `open_exposure_cents` by `quoted_price_cents`; cancelling from `QUOTED` releases nothing, because acceptance never happened. Either way the job's `version` bumps.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or upsert an existing resource return `200 OK`. In the table below, "All operational roles" means every role except `PlatformAdmin`: `Customer`, `SalesRep`, `CratingDesigner`, `ShopForeman`, `ComplianceOfficer`, `LogisticsCoordinator`, and `ClaimsAdjuster`. List endpoints accept the `limit` and `offset` pagination parameters of §2.3 plus optional filters: customers by `status`; packing jobs by `customer_id` and `status`; items by `packing_job_id` and `status`; designs by `item_id`, `wood_batch_id`, and `status`; wood batches by `status`; crates by `item_id`, `packing_job_id`, `container_id`, `design_id`, and `status`; declarations by `item_id` and `status`; packing lists and commercial invoices by `packing_job_id` and `status`; labor bookings by `crew_id`, `packing_job_id`, and `status`; permits by `packing_job_id`, `site_code`, and `status`; claims by `packing_job_id`, `crate_id`, and `status`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/crating/customers` | Create a Customer | SalesRep |
| GET | `/crating/customers/{id}` | Get a Customer | All operational roles |
| GET | `/crating/customers` | List Customers | SalesRep, CratingDesigner, ShopForeman, ComplianceOfficer, LogisticsCoordinator, ClaimsAdjuster |
| PATCH | `/crating/customers/{id}` | Update a Customer's name or credit limit | SalesRep |
| POST | `/crating/customers/{id}/suspend` | Suspend a Customer | SalesRep |
| POST | `/crating/customers/{id}/reinstate` | Reinstate a Customer | SalesRep |
| POST | `/crating/packing-jobs` | Create a PackingJob in `QUOTED` status | SalesRep |
| GET | `/crating/packing-jobs/{id}` | Get a PackingJob | All operational roles |
| GET | `/crating/packing-jobs` | List PackingJobs | All operational roles |
| PATCH | `/crating/packing-jobs/{id}` | Revise a quoted job's mode or incoterm (OCC) | SalesRep |
| POST | `/crating/packing-jobs/{id}/accept-quote` | Customer accepts the quote (`QUOTED` → `DESIGN`) | Customer |
| POST | `/crating/packing-jobs/{id}/start-packing` | Start packing (`DESIGN` → `PACKING`) | ShopForeman |
| POST | `/crating/packing-jobs/{id}/ship` | Ship the job (`LOADED` → `SHIPPED`) | LogisticsCoordinator |
| POST | `/crating/packing-jobs/{id}/deliver` | Deliver the job (`SHIPPED` → `DELIVERED`) | LogisticsCoordinator |
| POST | `/crating/packing-jobs/{id}/close` | Close the job and compute the final invoice (`DELIVERED` → `CLOSED`) | SalesRep |
| POST | `/crating/packing-jobs/{id}/cancel` | Cancel the job with full cascade (`QUOTED` or `DESIGN` → `CANCELLED`) | SalesRep |
| GET | `/crating/packing-jobs/{id}/quote` | Computed read: live provisional quote breakdown | All operational roles |
| POST | `/crating/packing-jobs/{id}/items` | Capture an item's dimensions, weight, and flags | SalesRep |
| GET | `/crating/items/{id}` | Get an Item | All operational roles |
| GET | `/crating/items` | List Items | All operational roles |
| PATCH | `/crating/items/{id}` | Correct an item's captured fields | SalesRep |
| POST | `/crating/items/{itemId}/designs` | Create a CrateDesign for an item (OCC; supersedes prior non-terminal designs) | CratingDesigner |
| GET | `/crating/designs/{id}` | Get a CrateDesign | All operational roles |
| GET | `/crating/designs` | List CrateDesigns | All operational roles |
| POST | `/crating/designs/{id}/submit` | Submit a design (`DRAFT` → `IN_REVIEW`) | CratingDesigner |
| POST | `/crating/designs/{id}/approve` | Approve a design, pinning a wood batch and reserving board feet (`IN_REVIEW` → `APPROVED`) | ComplianceOfficer |
| POST | `/crating/designs/{id}/reject` | Reject a design (`IN_REVIEW` → `REJECTED`) | ComplianceOfficer |
| POST | `/crating/designs/{id}/revise` | Revise a rejected design (`REJECTED` → `DRAFT`) | CratingDesigner |
| POST | `/crating/wood-batches` | Register an ISPM-15 certified lumber batch | ComplianceOfficer |
| GET | `/crating/wood-batches/{id}` | Get a WoodBatch (lazy expiry evaluation against the logical clock) | All operational roles |
| GET | `/crating/wood-batches` | List WoodBatches | SalesRep, CratingDesigner, ShopForeman, ComplianceOfficer, LogisticsCoordinator, ClaimsAdjuster |
| POST | `/crating/wood-batches/{id}/suspend` | Suspend a batch and cascade compliance holds (`ACTIVE` → `SUSPENDED`) | ComplianceOfficer |
| POST | `/crating/wood-batches/{id}/reinstate` | Reinstate a batch and clear compliance holds (`SUSPENDED` → `ACTIVE`) | ComplianceOfficer |
| POST | `/crating/items/{itemId}/crates` | Create a Crate pinning an approved design (design → `LOCKED`) | ShopForeman |
| GET | `/crating/crates/{id}` | Get a Crate | All operational roles |
| GET | `/crating/crates` | List Crates | All operational roles |
| POST | `/crating/crates/{id}/build` | Build a crate, consuming reserved wood (`PLANNED` → `BUILT`) | ShopForeman |
| POST | `/crating/crates/{id}/pack` | Pack a crate, recording protection devices (`BUILT` or `REOPENED` → `PACKED`) | ShopForeman |
| POST | `/crating/crates/{id}/seal` | Seal a crate, minting its ISPM-15 stamp serial (`PACKED` → `SEALED`) | ComplianceOfficer |
| POST | `/crating/crates/{id}/reopen` | Reopen a sealed crate, voiding its stamp (`SEALED` → `REOPENED`) | ShopForeman |
| POST | `/crating/items/{itemId}/hazmat-declarations` | Create a draft declaration for an item | ShopForeman, ComplianceOfficer |
| GET | `/crating/hazmat-declarations/{id}` | Get a HazmatDeclaration | All operational roles |
| GET | `/crating/hazmat-declarations` | List HazmatDeclarations | All operational roles |
| POST | `/crating/hazmat-declarations/{id}/submit` | Submit a declaration (`DRAFT` → `SUBMITTED`) | ShopForeman, ComplianceOfficer |
| POST | `/crating/hazmat-declarations/{id}/approve` | Approve a declaration (`SUBMITTED` → `APPROVED`; approver differs from preparer) | ComplianceOfficer |
| POST | `/crating/hazmat-declarations/{id}/reject` | Reject a declaration (`SUBMITTED` → `REJECTED`; SoD applies) | ComplianceOfficer |
| POST | `/crating/hazmat-declarations/{id}/revise` | Revise a rejected declaration (`REJECTED` → `DRAFT`) | ShopForeman, ComplianceOfficer |
| POST | `/crating/packing-jobs/{id}/packing-list` | Create or replace the job's PackingList | SalesRep |
| GET | `/crating/packing-lists/{id}` | Get a PackingList | All operational roles |
| GET | `/crating/packing-lists` | List PackingLists | All operational roles |
| POST | `/crating/packing-jobs/{id}/commercial-invoice` | Create or replace the job's CommercialInvoice | SalesRep |
| GET | `/crating/commercial-invoices/{id}` | Get a CommercialInvoice | All operational roles |
| GET | `/crating/commercial-invoices` | List CommercialInvoices | All operational roles |
| POST | `/crating/packing-jobs/{id}/finalize-docs` | Finalize both documents (`DRAFT` or `AMENDING` → `FINALIZED`) | SalesRep |
| POST | `/crating/packing-jobs/{id}/release-docs` | Release both documents after consistency checks (`FINALIZED` → `RELEASED`) | ComplianceOfficer |
| POST | `/crating/packing-jobs/{id}/amend-docs` | Reopen both documents for amendment (`RELEASED` → `AMENDING`, pre-shipment only) | SalesRep |
| POST | `/crating/crews` | Create a Crew | ShopForeman |
| GET | `/crating/crews/{id}` | Get a Crew | All operational roles |
| POST | `/crating/packing-jobs/{id}/labor-bookings` | Book crew time against a job | ShopForeman |
| GET | `/crating/labor-bookings/{id}` | Get a LaborBooking | All operational roles |
| GET | `/crating/labor-bookings` | List LaborBookings | All operational roles |
| POST | `/crating/labor-bookings/{id}/confirm` | Confirm a booking (`RESERVED` → `CONFIRMED`) | ShopForeman |
| POST | `/crating/labor-bookings/{id}/complete` | Complete a booking (`CONFIRMED` → `COMPLETED`) | ShopForeman |
| POST | `/crating/labor-bookings/{id}/cancel` | Cancel a booking (`RESERVED` or `CONFIRMED` → `CANCELLED`) | ShopForeman |
| POST | `/crating/packing-jobs/{id}/onsite-permit` | Request an on-site permit window | LogisticsCoordinator |
| GET | `/crating/onsite-permits/{id}` | Get an OnsitePermit | All operational roles |
| GET | `/crating/onsite-permits` | List OnsitePermits | All operational roles |
| POST | `/crating/onsite-permits/{id}/confirm` | Confirm a permit (`REQUESTED` → `CONFIRMED`) | LogisticsCoordinator |
| POST | `/crating/containers` | Create a Container | LogisticsCoordinator |
| GET | `/crating/containers/{id}` | Get a Container | All operational roles |
| POST | `/crating/containers/{id}/lock` | Lock a container (`PLANNING` → `LOCKED`; needs at least one loaded crate) | LogisticsCoordinator |
| POST | `/crating/containers/{id}/unlock` | Unlock a container (`LOCKED` → `PLANNING`; only when payload is zero) | LogisticsCoordinator |
| POST | `/crating/containers/{id}/load-crate` | Load a sealed crate into a container (`SEALED` → `LOADED`) | LogisticsCoordinator |
| POST | `/crating/containers/{id}/unload-crate` | Remove a loaded crate from a container (`LOADED` → `SEALED`) | LogisticsCoordinator |
| POST | `/crating/containers/{id}/gate-out` | Gate out a locked container (`LOCKED` → `GATED_OUT`) | LogisticsCoordinator |
| POST | `/crating/packing-jobs/{id}/claims` | File a damage claim against a delivered job | Customer |
| GET | `/crating/claims/{id}` | Get a DamageClaim | All operational roles |
| GET | `/crating/claims` | List DamageClaims | All operational roles |
| POST | `/crating/claims/{id}/review` | Open a claim for review (`FILED` → `UNDER_REVIEW`) | ClaimsAdjuster |
| POST | `/crating/claims/{id}/approve` | Approve a claim, computing the capped amount (`UNDER_REVIEW` → `APPROVED`) | ClaimsAdjuster |
| POST | `/crating/claims/{id}/deny` | Deny a claim (`UNDER_REVIEW` → `DENIED`) | ClaimsAdjuster |
| POST | `/crating/claims/{id}/settle` | Settle an approved claim, recording the paid/waived split (`APPROVED` → `SETTLED`) | ClaimsAdjuster |
| POST | `/crating/claims/{id}/appeal` | Appeal a denied claim once (`DENIED` → `UNDER_REVIEW`) | Customer |
| POST | `/crating/_clock/set_current_utc` | Set the logical clock (startup default is exactly 2026-08-01T00:00:00Z; never falls back to wall-clock time) | PlatformAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is described in the narrative of §2 and §3; this catalogue is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_JOB_INVALID_STATE` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_DESIGN_INVALID_STATE` | 409 Conflict |
| `ERR_CRATE_INVALID_STATE` | 409 Conflict |
| `ERR_DECLARATION_INVALID_STATE` | 409 Conflict |
| `ERR_DOC_INVALID_STATE` | 409 Conflict |
| `ERR_CONTAINER_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NO_APPROVED_DESIGN` | 409 Conflict |
| `ERR_PERMIT_REQUIRED` | 409 Conflict |
| `ERR_DOCS_NOT_RELEASED` | 409 Conflict |
| `ERR_OPEN_CLAIMS` | 409 Conflict |
| `ERR_ITEM_NOT_CAPTURABLE` | 409 Conflict |
| `ERR_ITEM_HAS_CRATE` | 409 Conflict |
| `ERR_HAZMAT_DECLARATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_BATCH_NOT_ACTIVE` | 409 Conflict |
| `ERR_DG_SEGREGATION_VIOLATION` | 422 Unprocessable Entity |
| `ERR_INDICATOR_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BARRIER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_UNQUALIFIED` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_PERMIT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_DOC_CRATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DOC_QUANTITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DOC_WEIGHT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVOICE_UNDERVALUED` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_WOOD` | 422 Unprocessable Entity |
| `ERR_STAMPS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_CONTAINER_OVERWEIGHT` | 422 Unprocessable Entity |
