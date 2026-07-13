# Recycling MRF & Commodity Settlement API — Product Requirements Document

## 1. Introduction

A Materials Recovery Facility (MRF) sits at the financial and physical crossroads of municipal recycling. Trucks arrive from partner municipalities carrying mixed recyclables; the facility weighs each load, audits its composition and contamination, sorts and bales the recovered commodities, ships those bales to mills against a moving commodity price index, and finally reconciles the money — rebates and penalties tied to contamination, revenue share owed back to the source municipality, and freight deducted from mill proceeds. This API is the system of record for that end-to-end flow.

The product exists to make settlement auditable and deterministic. Two calculations in the facility are inherently *provisional-then-final*: contamination adjustment (estimated from a sample at audit, then recomputed from measured residual at close) and bale value (snapshotted against the published index at baling, then recomputed against the index in force at settlement, net of freight). Because real money is posted to a municipal ledger at the "final" step and later possibly reversed on dispute, every posting is an append-only event and every derived balance is a pure function of those events. The remainder of this document specifies the entities, their state machines, the exact arithmetic, the validation ordering, and the REST contract that together guarantee that two correct implementations produce byte-identical ledgers.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an unrecognized value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the header pair is present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes five roles: `ScaleOperator`, `SortManager`, `CommodityTrader`, `SettlementClerk`, and `Municipality`. The first four are operational desks. A `ScaleOperator` registers inbound loads and performs composition audits. A `SortManager` manages sort lines, downtime, bales, load closing, and re-audit requests. A `CommodityTrader` manages mills, commodity indices, and the entire mill-shipment settlement lifecycle. A `SettlementClerk` onboards municipalities and produces and finalizes municipal statements. All four may also set the logical clock and may read any GET endpoint.

For each of the four operational roles — `ScaleOperator`, `SortManager`, `CommodityTrader`, and `SettlementClerk` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The `Municipality` role is different: it is entity-backed. When `X-User-Role` is `Municipality`, `X-User-ID` is the `id` of the acting `Municipality`, and any ownership check on a resource that references a municipality compares that resource's municipality foreign key to `X-User-ID`. A `Municipality` has no write operations of its own; it may only read (every GET endpoint is shared with all roles).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a common set of system-managed properties. Every resource is assigned an `id` — a server-minted UUID with no type prefix. Every resource records a `created_at`, an ISO 8601 UTC timestamp with three fractional digits captured when the resource was first created. Resources that can be modified after creation also carry an `updated_at` (same timestamp format, refreshed on every mutation) and a `version` — an integer that starts at 1 on creation and increments by one on every mutation of that resource. The `version` field additionally underpins optimistic concurrency control on municipalities, described in §2.7.

`Municipality`, `Mill`, `CommodityIndex`, `SortLine`, `DowntimeEvent`, `InboundLoad`, `Bale`, `MillShipment`, and `MunicipalStatement` all carry the full set (`id`, `created_at`, `updated_at`, `version`). The `RevenueSharePosting` is the sole exception: it is an append-only ledger event and carries only `id` and `created_at`. A posting has no `updated_at` and no `version`, because it is never modified after it is written — a correction is expressed by writing a further posting, never by editing an existing one.

Whenever the server recomputes a derived field on a resource — for example refreshing a `SortLine`'s `throughput_tph`, a `MillShipment`'s `total_net_tons`, or a `Municipality`'s `balance_cents` — that recomputation is a mutation: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Monetary and Mass Precision

All monetary amounts in the system are integers denominated in **cents**; there are no fractional cents. Every calculation that produces a cents amount rounds its real-valued result to the nearest whole cent using the **round half up** convention (a value exactly halfway between two integers rounds away from zero in magnitude toward the next integer). This applies to contamination adjustments, gross bale values, freight shares, per-bale revenue-share amounts, and every other cents-valued output described in §3.

Tonnage quantities are decimal and are carried to three decimal places. Throughput, described in §2.8 and §3.3, is carried to two decimal places. Where an ordering of operations affects the result of rounding — most importantly when summing many already-rounded per-bale amounts into a shipment total — the pinned order is specified explicitly in the relevant workflow and must be honored, because rounding-then-summing and summing-then-rounding can differ by several cents.

### 2.6. The Municipal Revenue Ledger

Each `Municipality` owns a running ledger that is never edited in place. Instead, the facility appends `RevenueSharePosting` events, and the municipality's stored counters are the accumulated projection of those events. A posting records the `municipality_id` it applies to, a `posting_type`, a signed `amount_cents`, optional audit references `related_bale_id` and `related_load_id` pointing at whatever produced it, and a `reversed` flag that starts false and becomes true once a compensating reversal has offset it.

There are four posting types. A `REVENUE_SHARE` posting credits the municipality its share of a settled bale's value. A `REBATE` posting credits the municipality for a clean (low-contamination) load. A `PENALTY` posting debits the municipality for an over-contaminated load; its magnitude is stored as a positive number even though it reduces what the municipality is owed. A `REVERSAL` posting carries the negation of a prior `REVENUE_SHARE` and is written when a settled shipment is disputed.

Three counters on the municipality accumulate these events. `revenue_share_accrued_cents` is the running sum of `REVENUE_SHARE` postings net of their `REVERSAL`s. `lifetime_rebate_cents` is the running sum of `REBATE` postings. `lifetime_penalty_cents` is the running sum of `PENALTY` posting magnitudes (stored positive). From these, the net amount owed to the municipality, `balance_cents`, is derived as `revenue_share_accrued_cents` plus `lifetime_rebate_cents` minus `lifetime_penalty_cents`. All four counters initialize to 0 when a municipality is created. Any posting that touches a municipality re-derives `balance_cents` and, as a mutation, advances the municipality's `version` and `updated_at`.

### 2.7. Optimistic Concurrency on Municipal Statement Creation

Creating a municipal statement is guarded by optimistic concurrency against the target municipality. The create request must include `expected_municipality_version`, carrying the client's last observed `version` of that `Municipality`. Before creating the statement, the server compares `expected_municipality_version` to the municipality's current `version`; if they differ, the client's view is stale — some other write (a prior statement creation, or a close or settlement cascade that posted to the ledger) has advanced the municipality since the client last read it — and the create is rejected with `ERR_STALE_MUNICIPALITY_VERSION` at HTTP 412. This check is evaluated after the municipality is confirmed to exist and before any business logic runs. Because a fresh statement is meant to replace an earlier draft, a successful create supersedes the municipality's current `OPEN` statement and then advances the municipality's `version` by one, so a second create attempted with the same `expected_municipality_version` will correctly fail. No other endpoint accepts a version field; concurrency control exists only on statement creation.

### 2.8. Resource Resolution, Filtered Retrieval, and Throughput

Although the data model is flat — resources reference one another by foreign-key ids rather than through nested URL paths — many operations name several resources at once (in the path or the body). When a request references multiple resource ids, the server validates their existence left-to-right and rejects at the first id that does not resolve, returning the not-found error specific to that resource type: `ERR_MUNICIPALITY_NOT_FOUND`, `ERR_MILL_NOT_FOUND`, `ERR_INDEX_NOT_FOUND`, `ERR_SORT_LINE_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_BALE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, or the generic `ERR_NOT_FOUND` for a downtime event or a posting.

Because there are no nested URLs, every foreign-key relationship is reachable through a filtered list. Inbound loads can be filtered by `source_municipality_id`, `sort_line_id`, and `status`; bales by `source_load_id`, `shipment_id`, `status`, and `commodity`; mill shipments by `mill_id` and `status`; commodity indices by `commodity` and `status`; downtime events by `sort_line_id`; municipal statements by `municipality_id` and `status`; and revenue postings by `municipality_id`.

A sort line continuously reports operational health. `total_processed_tons` is the sum of `net_tons` over the inbound loads assigned to that line that have reached `CLOSED`. `total_downtime_minutes` is the sum of `downtime_minutes` over the line's downtime events. From these, `throughput_tph` is the processed tonnage divided by the line's uptime in hours, where uptime hours equals the line's `scheduled_shift_minutes` minus `total_downtime_minutes`, all divided by 60; the quotient is rounded to two decimal places. When uptime hours is zero or negative, `throughput_tph` is reported as 0 rather than computed.

### 2.9. The Logical Clock and Index-Window Selection

The system runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. An administrative capability lets any operational role set the clock to a supplied instant, `to_iso8601`. The clock governs the `created_at` stamp written on every new resource and posting, and it governs which commodity index is "in force."

A commodity index defines a half-open price window: `effective_start` is inclusive and `effective_end` is exclusive. An index is "in force for a commodity at an instant" when the index is `PUBLISHED`, its `commodity` matches, and the instant falls at or after `effective_start` and strictly before `effective_end`. This selection rule is what supplies the price used for bale valuation snapshots at baling and for final valuation at settlement (§3.2, §3.6, §3.7).

### 2.10. Order of Request Validation

When several checks could reject one request, they are evaluated in a fixed priority order so that the reported error is deterministic. The order is: (1) presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400); (2) whether the role is permitted for the operation (`ERR_INSUFFICIENT_PERMISSIONS`, 403); (3) existence of every referenced resource, left-to-right (the applicable 404); (4) the optimistic-concurrency version match on statement creation (`ERR_STALE_MUNICIPALITY_VERSION`, 412); (5) whether the target entity is in the state the requested transition requires (a 409 state error); (6) cross-entity referential readiness, such as a published index existing at settlement or a bale's source load being closed before it is assigned (422); (7) safety and commodity-validity checks such as contamination being processable and a bale's commodity being recognized (422); (8) interval-overlap checks for downtime windows and index windows (409); (9) quantity and interval feasibility such as valid intervals, residual not exceeding net, bale tonnage within remaining, and a shipment being non-empty (422); and finally (10) fiscal range checks such as revenue-share fraction and percentage bounds (422). A malformed body, a missing required field, or a type mismatch surfaces as `ERR_INVALID_REQUEST` (400).

## 3. Business Logic & Workflows

### 3.1. Onboarding Municipalities and Mills

A `SettlementClerk` registers a partner municipality by supplying its `name`, an optional `contact_email`, and its `revenue_share_pct` — the fraction of settled commodity revenue that flows back to the municipality. That fraction must lie between 0 and 1 inclusive; a value below 0 or above 1 is rejected with `ERR_REVENUE_SHARE_PCT_OUT_OF_RANGE`. A new municipality begins with `status` of `ACTIVE` (the alternative operational value is `SUSPENDED`) and with all four ledger counters — `revenue_share_accrued_cents`, `lifetime_rebate_cents`, `lifetime_penalty_cents`, and the derived `balance_cents` — initialized to 0, as described in §2.6.

Separately, a `CommodityTrader` registers a mill (a commodity buyer) by supplying its `name`, its `commodity_focus`, and a reference `freight_rate_cents_per_ton`. The `commodity_focus`, like every commodity-typed field in the system, is one of `OCC`, `MIXED_PAPER`, `PET`, `HDPE`, `ALUMINUM`, `STEEL`, or `GLASS`. The `freight_rate_cents_per_ton` is documentation only and does not enter any settlement arithmetic — actual freight is charged per shipment (§3.7). A mill begins with `status` of `ACTIVE` and may later be `INACTIVE`.

### 3.2. Commodity Price Index Windows

A `CommodityTrader` publishes the price signal the facility settles against. Creating an index registers a `commodity`, a `price_cents_per_ton`, and a half-open effective window bounded by `effective_start` (inclusive) and `effective_end` (exclusive); a new index begins in `DRAFT`. Publishing an index advances it from `DRAFT` to `PUBLISHED`. Publication is only permitted on an index currently in `DRAFT`; otherwise it is rejected with `ERR_INDEX_NOT_DRAFT`. The window must be well-formed — `effective_start` must be strictly earlier than `effective_end`, or the request fails with `ERR_INVALID_INTERVAL`. Finally, the new window must not overlap any existing `PUBLISHED` index for the same commodity; because the windows are half-open, mere adjacency (one window's `effective_end` equal to the next window's `effective_start`) is permitted, but any true overlap is rejected with `ERR_INDEX_WINDOW_OVERLAP`.

Publication can retire an earlier window automatically. When an index is published whose `effective_start` is strictly later than that of the most recent prior `PUBLISHED` index for the same commodity, and the two windows are adjacent (the prior index's `effective_end` equals the new index's `effective_start`), the system transitions that prior index from `PUBLISHED` to `SUPERSEDED` in a single hop. `SUPERSEDED` is terminal.

### 3.3. Sort Lines and Downtime

A `SortManager` provisions a sort line with a `name`, a `rated_tph` (its rated tons-per-hour capacity), and an optional `scheduled_shift_minutes`; when the shift length is omitted it defaults to 480 minutes. A line begins with `status` of `IDLE` (its other operational values are `RUNNING` and `DOWN`) and with `total_processed_tons`, `total_downtime_minutes`, and `throughput_tph` all initialized to 0.

The same manager records downtime against a line by supplying the line's `sort_line_id`, a `start_at`, an `end_at`, and a free-text `reason`. The window must be well-formed — `end_at` strictly after `start_at`, else `ERR_INVALID_INTERVAL`. A downtime window may not conflict with any existing downtime event on the same line: these are treated as closed intervals, so even touching endpoints (adjacency) count as a conflict, and any such collision is rejected with `ERR_DOWNTIME_OVERLAP`. On acceptance the event's `downtime_minutes` is computed as the number of whole minutes between `start_at` and `end_at`, taking the floor of any fractional minute, and the owning line's `total_downtime_minutes` and `throughput_tph` are recomputed per the definitions in §2.8.

### 3.4. Receiving and Auditing Inbound Loads

A `ScaleOperator` registers an inbound load at the weighbridge by supplying the delivering municipality's `source_municipality_id`, the assigned line's `sort_line_id`, the `hauler` name, the `gross_tons` read on the bridge, and the truck's `tare_tons`. The load's conserved net weight, `net_tons`, is computed as `gross_tons` minus `tare_tons`; this quantity is the anchor of mass balance and never changes thereafter. A new load enters in `RECEIVED` status.

Auditing a load records what was actually in it. The operator supplies the `sampled_contamination_pct` measured from a grab sample and the `audited_composition` — a list in which each entry names a `commodity` and its `pct` share of the load. An audit may only run on a load in `RECEIVED` or `PENDING_REAUDIT`; attempting it in any other state yields `ERR_LOAD_NOT_AUDITABLE`. The sampled contamination must be strictly below the reject threshold of 40 percent; a load at or above that contamination is unprocessable and the audit is refused with `ERR_CONTAMINATION_UNPROCESSABLE`. Every composition percentage, and the sampled contamination, must fall within 0 to 100 inclusive, else the body is rejected as `ERR_INVALID_REQUEST`. A successful audit stores the sampled contamination and composition, computes and stores the load's `provisional_adjustment_cents` from the sampled figure (the provisional variant of the contamination calculation described in §3.5), and moves the load to `AUDITED`. Re-auditing a load that returned to `PENDING_REAUDIT` overwrites the stored sample and composition and recomputes `provisional_adjustment_cents` the same way.

A `SortManager` may send an `AUDITED` load back for correction, supplying a `reason`; this drives the revision loop `AUDITED → PENDING_REAUDIT`, forcing a fresh audit. Re-audit may only be requested on a load actually in `AUDITED`, and only while no non-`VOIDED` bales exist for that load; either violation is reported as `ERR_LOAD_INVALID_STATE`.

### 3.5. Closing Loads: Residual, Final Adjustment, and the Ledger Cascade

Closing a load is where contamination money becomes real. A `SortManager` closes an `AUDITED` load by supplying the `residual_tons` — the tonnage sent to disposal. Closing is only permitted from `AUDITED`; otherwise `ERR_LOAD_NOT_AUDITED`. The residual plus whatever has already been baled must not exceed the load's net weight — that is, `residual_tons` plus `baled_tons` must be at most `net_tons`, else `ERR_RESIDUAL_EXCEEDS_NET`.

The contamination adjustment itself is a tiered calculation over a contamination percentage and the load's `net_tons`, and it is evaluated in two variants that share one formula. If contamination is at most the clean threshold of 5.0 percent, the load earns a rebate: the adjustment is a positive amount equal to `net_tons` multiplied by 300 cents per ton, rounded half up to whole cents. If contamination is at least the penalty threshold of 12.0 percent, the load incurs a penalty: let the points over threshold be the contamination percentage minus 12.0; the adjustment is a negative amount whose magnitude is `net_tons` multiplied by those points-over multiplied by 150 cents per ton-per-point, rounded half up to whole cents. Contamination strictly between 5.0 and 12.0 yields an adjustment of exactly 0. The thresholds are inclusive on both sides: exactly 5.0 is a rebate, and exactly 12.0 is a penalty of zero points, which evaluates to 0.

The **provisional variant** runs at audit: it uses `sampled_contamination_pct` as the contamination input, stores its result in `provisional_adjustment_cents`, and does **not** post anything to the ledger. The **final variant** runs at close: its contamination input is the residual-derived actual, computed as `residual_tons` divided by `net_tons`, multiplied by 100, rounded to four decimal places. The final result is stored in `final_adjustment_cents` and is posted to the municipality. Concretely, closing cascades as follows: first, a `RevenueSharePosting` is created for the load's `source_municipality_id` with `amount_cents` equal to `final_adjustment_cents` — typed `REBATE` when that amount is positive and `PENALTY` when it is negative; second, that posting updates the municipality's `lifetime_rebate_cents` or `lifetime_penalty_cents` (penalties stored as positive magnitude), re-derives `balance_cents`, and increments the municipality's `version`. In the same transaction the assigned line's `total_processed_tons` gains this load's `net_tons` and its `throughput_tph` is recomputed, the load's `residual_tons` and `unbaled_remaining_tons` are stored, and the load moves to `CLOSED`.

Mass is conserved throughout a load's life. At any moment `baled_tons` is the sum of `net_tons` over the load's non-`VOIDED` bales, and `unbaled_remaining_tons` equals `net_tons` minus `baled_tons` minus `residual_tons`; the three components — baled, residual, and unbaled — always sum back to `net_tons`.

### 3.6. Baling and the Provisional Bale Value

A `SortManager` bales recovered material off an audited load. Creating a bale references its `source_load_id` and declares the bale's `commodity`, its baled `net_tons`, its `moisture_pct` dockage, and its `quality_grade` (one of `A`, `B`, or `C`). The source load must be in `AUDITED` at bale time, else `ERR_LOAD_NOT_AUDITED`. The declared commodity must actually appear in that load's `audited_composition`; a commodity absent from the audit is refused with `ERR_COMMODITY_NOT_IN_LOAD`. The bale's `net_tons` may not exceed the load's current `unbaled_remaining_tons`, else `ERR_BALE_TONS_EXCEED_REMAINING`. A new bale begins in `BALED` status, with its `shipment_id` empty until it is later assigned.

At creation the bale captures a price snapshot and a provisional value. The `index_price_snapshot_cents` is the `price_cents_per_ton` of the index in force for the bale's commodity at the bale's creation instant (per §2.9). The provisional value is then computed by the bale valuation formula: first compute effective tonnage as `net_tons` multiplied by the quantity one minus `moisture_pct` divided by 100; multiply by the grade multiplier, which is 1.00 for grade `A`, 0.90 for grade `B`, and 0.75 for grade `C`; and round that product, taken against `index_price_snapshot_cents`, half up to whole cents. In the provisional variant there is no freight deduction, so `provisional_value_cents` is exactly that rounded gross value. Creating a bale also increases the source load's `baled_tons` by the bale's `net_tons` and correspondingly reduces its `unbaled_remaining_tons`.

Bales can be withdrawn before they ship. A `SortManager` voids a bale that is still in `BALED` or `STAGED`; a bale already `SHIPPED` or `SETTLED` cannot be voided, and any such attempt is `ERR_BALE_NOT_VOIDABLE`. Voiding moves the bale to `VOIDED` (terminal), clears its `shipment_id`, and — if the bale had been staged onto a shipment — recomputes that shipment's `total_net_tons`. Voiding also returns mass to the source load: the load's `baled_tons` drops by the voided bale's `net_tons` and its `unbaled_remaining_tons` is restored by the same amount, leaving `net_tons` unchanged.

### 3.7. Mill Shipments: Building, Shipping, Settling, and Disputing

A `CommodityTrader` assembles material for a buyer by creating a mill shipment against a `mill_id`, a `commodity`, and a `freight_cost_cents` — the total freight for the shipment, which will be allocated across its bales at settlement. A shipment begins in `BUILDING`.

Assigning a bale to a shipment moves that bale from `BALED` to `STAGED`. The assignment request identifies the bale by `bale_id`. The shipment must still be `BUILDING`, or the assignment is refused with `ERR_SHIPMENT_NOT_BUILDING`; the bale must be in `BALED`, or `ERR_BALE_NOT_STAGEABLE`; the bale's `commodity` must equal the shipment's `commodity`, or `ERR_COMMODITY_MISMATCH`; and the bale's source load must already be `CLOSED`, or `ERR_BALE_LOAD_NOT_CLOSED`. On success the bale's `shipment_id` is set, the bale becomes `STAGED`, and the shipment's `total_net_tons` — the sum of `net_tons` over its assigned, non-`VOIDED` bales — is recomputed.

Shipping requires at least one `STAGED` bale; an attempt to ship an empty shipment is rejected with `ERR_SHIPMENT_EMPTY`, and shipping is only allowed from `BUILDING`, else `ERR_SHIPMENT_NOT_BUILDING`. Shipping advances the shipment from `BUILDING` to `SHIPPED` and carries all its `STAGED` bales to `SHIPPED` with it.

Settlement is where mill proceeds and municipal revenue share are computed. Settling is permitted only from `SHIPPED` or `DISPUTED`; any other state is `ERR_SHIPMENT_NOT_SHIPPED`. Settlement further requires that an index be in force for the shipment's `commodity` at the current clock; if none is, the settle is refused with `ERR_NO_PUBLISHED_INDEX`. When settlement proceeds, each `SHIPPED` bale is settled in turn. First, freight is allocated: each bale's `freight_share_cents` is the shipment's `freight_cost_cents` multiplied by that bale's `net_tons` divided by the shipment's `total_net_tons`, rounded half up to whole cents. Then the bale's `final_value_cents` is computed by the final variant of the bale valuation: the same effective-tonnage-times-grade-multiplier product as before, but priced at the `price_cents_per_ton` of the index in force at the settle-time clock (which may differ from the snapshot taken at baling), rounded once to whole cents, and then reduced by that bale's `freight_share_cents`. The evaluation order is pinned: compute effective tonnage, apply the grade multiplier, round to cents, and only then subtract freight. Each settled bale moves from `SHIPPED` to `SETTLED`.

Two aggregates follow. The shipment's `gross_settlement_cents` is the sum of the per-bale `final_value_cents` values — and because each `final_value_cents` is already an integer number of cents, the total is the sum of those per-bale integers (round each bale first, then add), never a single rounding of summed real values; the two orders can differ by up to one cent per additional bale. And for each settled bale, revenue share is posted to the bale's source municipality: the source municipality is the one on the bale's source load (`source_municipality_id`), and the per-bale share is that bale's `final_value_cents` multiplied by the municipality's `revenue_share_pct`, rounded half up to whole cents. That share is written as a `REVENUE_SHARE` posting whose `amount_cents` credits the municipality; the posting raises the municipality's `revenue_share_accrued_cents`, re-derives `balance_cents`, and increments the municipality's `version`. The shipment ends in `SETTLED`.

Disputing reverses a settlement. A dispute is permitted only from `SETTLED`, else `ERR_SHIPMENT_NOT_SETTLED`, and takes a `reason`. It moves the shipment from `SETTLED` to `DISPUTED` and carries each `SETTLED` bale back to `SHIPPED`. For every `REVENUE_SHARE` posting produced for such a bale that has not already been reversed, a `REVERSAL` posting is written whose `amount_cents` is the negation of the original, and the original's `reversed` flag is set true; the municipality's `revenue_share_accrued_cents` and `balance_cents` are thereby restored to their pre-settlement values (money conservation), and its `version` advances. Each disputed bale's `final_value_cents` is reset to 0 and the shipment's `gross_settlement_cents` is reset to 0. A disputed shipment can be settled again, recomputing final values, re-posting revenue share, and recomputing `gross_settlement_cents`, returning it to `SETTLED`.

### 3.8. Municipal Statements

A `SettlementClerk` produces a municipal statement for a reporting period. Creating a statement references the `municipality_id`, a `period_start` (inclusive) and a `period_end` (exclusive), and the `expected_municipality_version` that guards the create under optimistic concurrency (§2.7). A new statement begins in `OPEN`; a successful create supersedes the municipality's prior `OPEN` statement — driving that earlier statement from `OPEN` to `SUPERSEDED` — and advances the municipality's `version` by one.

Finalizing a statement is permitted only from `OPEN`, else `ERR_STATEMENT_NOT_OPEN`. Finalization aggregates that municipality's postings whose `created_at` falls within the half-open period window — at or after `period_start` and strictly before `period_end` — summing them in `created_at` ascending order for determinism. From that set, `total_revenue_share_cents` is the sum of the `amount_cents` of `REVENUE_SHARE` postings plus the sum of the `amount_cents` of `REVERSAL` postings (reversals being negative, they reduce the total). `total_rebate_cents` is the sum of the `amount_cents` of `REBATE` postings (positive). `total_penalty_cents` is the sum of the magnitudes of `PENALTY` postings (each stored positive). Finally `net_payable_cents` is `total_revenue_share_cents` plus `total_rebate_cents` minus `total_penalty_cents`. The statement then moves to `FINALIZED`.

## 4. Endpoint Definitions

Operations that create a brand-new, standalone resource return `201 Created`. State-transition and modification operations, and the logical-clock capability, return `200 OK`. List and single-item reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ScaleOperator, SortManager, CommodityTrader, SettlementClerk |
| POST | `/mrf/municipalities` | Create a municipality | SettlementClerk |
| GET | `/mrf/municipalities/{municipalityId}` | Get a municipality (includes ledger balance) | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| POST | `/mrf/mills` | Create a mill / buyer | CommodityTrader |
| GET | `/mrf/mills/{millId}` | Get a mill | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| POST | `/mrf/commodity-indices` | Create a commodity price index window (DRAFT) | CommodityTrader |
| GET | `/mrf/commodity-indices` | List commodity indices (filterable) | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| GET | `/mrf/commodity-indices/{indexId}` | Get a commodity index | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| POST | `/mrf/commodity-indices/{indexId}/publish` | Publish a DRAFT index | CommodityTrader |
| POST | `/mrf/sort-lines` | Create a sort line | SortManager |
| GET | `/mrf/sort-lines/{sortLineId}` | Get a sort line (includes computed throughput) | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| POST | `/mrf/downtime-events` | Record a downtime window on a sort line | SortManager |
| GET | `/mrf/downtime-events` | List downtime events (filterable) | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| GET | `/mrf/downtime-events/{downtimeEventId}` | Get a downtime event | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| POST | `/mrf/inbound-loads` | Register an inbound load | ScaleOperator |
| GET | `/mrf/inbound-loads` | List inbound loads (filterable) | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| GET | `/mrf/inbound-loads/{loadId}` | Get an inbound load | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| POST | `/mrf/inbound-loads/{loadId}/audit` | Record composition audit and sampled contamination | ScaleOperator |
| POST | `/mrf/inbound-loads/{loadId}/request-reaudit` | Send an AUDITED load back for re-audit | SortManager |
| POST | `/mrf/inbound-loads/{loadId}/close` | Close an audited load; finalize contamination adjustment | SortManager |
| POST | `/mrf/bales` | Create a bale from an audited load | SortManager |
| GET | `/mrf/bales` | List bales (filterable) | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| GET | `/mrf/bales/{baleId}` | Get a bale | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| POST | `/mrf/bales/{baleId}/void` | Void a bale (BALED or STAGED) | SortManager |
| POST | `/mrf/mill-shipments` | Create a mill shipment (BUILDING) | CommodityTrader |
| GET | `/mrf/mill-shipments` | List mill shipments (filterable) | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| GET | `/mrf/mill-shipments/{shipmentId}` | Get a mill shipment | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| POST | `/mrf/mill-shipments/{shipmentId}/bales` | Assign a bale to a BUILDING shipment | CommodityTrader |
| POST | `/mrf/mill-shipments/{shipmentId}/ship` | Ship a shipment (requires >=1 staged bale) | CommodityTrader |
| POST | `/mrf/mill-shipments/{shipmentId}/settle` | Settle a shipped/disputed shipment | CommodityTrader |
| POST | `/mrf/mill-shipments/{shipmentId}/dispute` | Dispute a settled shipment | CommodityTrader |
| POST | `/mrf/municipal-statements` | Create a municipal statement (OCC on Municipality.version) | SettlementClerk |
| GET | `/mrf/municipal-statements` | List municipal statements (filterable) | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| GET | `/mrf/municipal-statements/{statementId}` | Get a municipal statement | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| POST | `/mrf/municipal-statements/{statementId}/finalize` | Finalize an OPEN statement | SettlementClerk |
| GET | `/mrf/revenue-postings` | List revenue-share / adjustment postings (filterable) | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |
| GET | `/mrf/revenue-postings/{postingId}` | Get a revenue-share posting | ScaleOperator, SortManager, CommodityTrader, SettlementClerk, Municipality |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_MUNICIPALITY_NOT_FOUND` | 404 Not Found |
| `ERR_MILL_NOT_FOUND` | 404 Not Found |
| `ERR_INDEX_NOT_FOUND` | 404 Not Found |
| `ERR_SORT_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_LOAD_NOT_FOUND` | 404 Not Found |
| `ERR_BALE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_REVENUE_SHARE_PCT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_STALE_MUNICIPALITY_VERSION` | 412 Precondition Failed |
| `ERR_LOAD_NOT_AUDITABLE` | 409 Conflict |
| `ERR_LOAD_NOT_AUDITED` | 409 Conflict |
| `ERR_LOAD_INVALID_STATE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_BUILDING` | 409 Conflict |
| `ERR_SHIPMENT_NOT_SHIPPED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_SETTLED` | 409 Conflict |
| `ERR_BALE_NOT_STAGEABLE` | 409 Conflict |
| `ERR_BALE_NOT_VOIDABLE` | 409 Conflict |
| `ERR_INDEX_NOT_DRAFT` | 409 Conflict |
| `ERR_STATEMENT_NOT_OPEN` | 409 Conflict |
| `ERR_NO_PUBLISHED_INDEX` | 422 Unprocessable Entity |
| `ERR_BALE_LOAD_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_CONTAMINATION_UNPROCESSABLE` | 422 Unprocessable Entity |
| `ERR_COMMODITY_NOT_IN_LOAD` | 422 Unprocessable Entity |
| `ERR_COMMODITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DOWNTIME_OVERLAP` | 409 Conflict |
| `ERR_INDEX_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_RESIDUAL_EXCEEDS_NET` | 422 Unprocessable Entity |
| `ERR_BALE_TONS_EXCEED_REMAINING` | 422 Unprocessable Entity |
| `ERR_SHIPMENT_EMPTY` | 422 Unprocessable Entity |
