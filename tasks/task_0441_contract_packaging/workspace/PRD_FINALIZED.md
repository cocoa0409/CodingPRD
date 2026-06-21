# Contract Packaging API — Product Requirements Document

## 1. Introduction

Contract packaging — also called co-packing — is the business of running another company's product through your own lines. A brand owner supplies the recipe and, often, the raw materials; the co-packer owns the lines, crews, and quality apparatus, and turns those inputs into finished, lot-coded, date-stamped goods. This API is the system of record for that operation. It tracks the brand owners we pack for, the components and physical inventory lots they supply, the recipes and bills of materials that describe how a unit is built, the lines and crews that execute the work, and the production runs that consume inventory and emit finished goods.

The product exists to make three hard problems auditable and safe. First, **material traceability and ownership**: when a customer owns the components, every gram drawn, scrapped, or returned must reconcile against that customer's ledger so we can prove we neither lost nor kept their material. Second, **food-safety changeover and quality control**: a line carrying peanut residue must not silently run a peanut-free product, expired lots must never be consumed, and a run cannot ship until its checkweigher samples prove the fill weights are in tolerance. Third, **scheduling integrity**: lines and crews are finite, runs must not collide, and the recipe driving a run must have cleared quality approval before a single unit is packed.

The remainder of this document specifies the global contracts every endpoint obeys (Section 2), the business workflows and the rules scattered through them (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The entire surface is mounted under `/copack`.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles: `Receiver`, `Scheduler`, and `QAInspector`. A request that omits either header, or whose `X-User-Role` is not one of these three known roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED`.

The three roles partition the surface into distinct ownership slices, with all read (GET) operations and the logical-clock control shared by all three. A `Receiver` owns warehouse intake: registering brand-owner customers, creating the components those customers supply, and receiving inbound physical lots into inventory. A `Scheduler` owns production planning: authoring recipes and their bill-of-materials lines, defining lines and crews, and scheduling, starting, completing, and cancelling runs. A `QAInspector` owns quality: approving and rejecting recipes, recording checkweigher samples, releasing and quarantining runs, and recording sanitation cleanouts.

For all three roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`; ownership and permission decisions are made purely on `X-User-Role` and the operation being attempted, not on which specific operator is acting.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits stamped when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that begins at its initial value on creation and increments by one on every mutation of the resource; it is the basis for the optimistic concurrency control described in Section 2.7.

A handful of entities are append-only records that carry only `id` and `created_at` — they have no `updated_at` and no `version`, because once written they are never mutated. These are: the `LotConsumption` record (one row per physical lot drawn against a bill-of-materials line during a run), the `CheckweighSample` record (one scale reading), the `CmrLedgerEntry` record (one signed adjustment to a customer's reconciled balance), and the `SanitationEvent` record (one line cleanout). All other entities — `Customer`, `Component`, `ComponentLot`, `Recipe`, `BomLine`, `ProductionLine`, `Crew`, and `ProductionRun` — carry the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Hierarchical Consistency and Cascading Effects

Many operations in this domain mutate more than one entity in a single atomic step, and each affected entity is independently re-stamped: its `updated_at` is refreshed and its `version` is incremented by one. When a run draws down inventory, for example, the run, every touched physical lot, and every affected component are all mutated together, and each carries its own version bump. The detailed cascade for each operation lives in the workflow narratives of Section 3; the global principle is that the system never leaves a partially reconciled state, and that derived quantities such as a component's on-hand balance are recomputed immediately whenever an event that affects them occurs (the consistency model is immediate, not eventual).

### 2.6. Nested Resource Retrieval and Existence Ordering

Several paths address a child resource through its parent — for instance, a recipe's bill-of-materials lines, a line's sanitation events, or a run's checkweigh samples. For any such request, the system validates the path identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before considering any later segment. The same existence rule governs foreign-key references supplied in a request body: a create that names a `customer_id`, `component_id`, `recipe_id`, `line_id`, or `crew_id` that does not exist is rejected with `ERR_NOT_FOUND`.

### 2.7. Optimistic Concurrency Control

Two write operations in this system require the client to prove it is acting on a current view of a parent resource, guarding against a writer overwriting state it has not observed.

Starting a production run mutates the line it runs on (it stamps the line's allergen residue), so the start request must carry `expected_line_version`, the client's last observed `version` of the referenced `ProductionLine`. If that value does not equal the line's current `version` — for example, because another run started on the same line and advanced its residue since the client last read it — the start is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client holding a stale line view from running an allergen-changeover decision against out-of-date residue.

Adding a bill-of-materials line to a recipe likewise requires `expected_recipe_version`, the client's last observed `version` of the target `Recipe`. If that value does not equal the recipe's current `version` — for example, because a submit recomputed the recipe's allergen profile and bumped its version since the client last read it — the add is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from appending a line to a recipe it has not observed in its current form.

No other endpoint takes a version field; only run-start and bom-line-add participate in concurrency control.

### 2.8. Precision and Rounding

All quantity figures — required draws, consumed quantities, waste, and on-hand balances — are computed to three decimal places using the round-half-up method. The checkweigher reject rate is computed to four decimal places, round half up. A run's realized throughput is computed to two decimal places, round half up. The fill-tolerance band endpoints used to judge a sample are themselves rounded half up to three decimal places before the comparison, and a sample's measured weight is compared to those endpoints in grams to three decimals. Where Section 3 describes a total that is itself a sum of per-line figures, the rounding order is pinned and stated explicitly at that point.

### 2.9. Allergen Changeover and Line Sanitation

A line carries an allergen memory: after a run starts on a line, the line records the allergen set of that run's recipe as its current residue. Before a different recipe may run, the system enforces a changeover safety check (detailed in Section 3) so that a line dirty with an allergen the incoming recipe does not declare cannot pack that recipe. The memory is cleared only by a deliberate sanitation cleanout, recorded by a `QAInspector`, which snapshots and then empties the line's residue. This is a cross-cutting safety invariant that interlocks with run scheduling, run start, and optimistic concurrency on the line.

### 2.10. Customer-Owned Material Reconciliation

When a brand owner supplies its own materials, every movement of that material must net out on a ledger so that ownership can be proven at audit. Components belonging to such a customer are flagged customer-owned at creation time, and from then on every consumption, every scrap loss, and every compensating return tied to a run emits a signed ledger entry. The sign convention, the reasons, and the net-to-zero guarantee on cancellation are specified within the relevant run-lifecycle narratives in Section 3; the principle here is that a customer-owned component's reconciled balance is always reconstructable from the sum of its ledger entries.

### 2.11. The Logical Clock

Time in this system is a server-controlled logical clock rather than wall-clock time. The clock drives a run's pack date, judges lot expiry at run start, and measures elapsed time for throughput. On server startup the clock reads exactly `2026-01-01T00:00:00Z` and never falls back to wall-clock time; before any explicit set, every time-dependent computation uses that default. Any of the three roles may advance the clock by supplying a target instant in the `to_iso8601` field, after which the clock reports the new `current_utc`.

## 3. Business Logic & Workflows

### 3.1. Brand Owners, Components, and Inbound Inventory

The foundation of the system is the brand owner we pack for. A `Receiver` registers a customer by supplying its legal `name` and a short `code` — two to six uppercase alphanumeric characters that must be unique across all customers; a collision is rejected with `ERR_DUPLICATE_CODE`. This code later becomes the leading element of every finished-goods lot code, so it is treated as a stable identifier. A customer also declares, through the `owns_components` flag, whether the materials it supplies are its own property; this flag defaults to false when omitted, and when true it marks every component the customer supplies as material the co-packer holds on the customer's behalf.

A `Receiver` then creates the components a customer supplies. A component names its owning `customer_id`, a `sku` that must be unique within that one customer (the same SKU string may recur under a different customer, but a repeat within the same `customer_id` is rejected with `ERR_DUPLICATE_SKU`), a human-readable `name`, and a `kind` that classifies the component's role as one of `INGREDIENT`, `PACKAGING`, or `LABEL`. A value of `kind` outside that set is rejected with `ERR_INVALID_ENUM`. A component also declares its `allergens` as a set of allergen codes — for example milk or peanut codes — which defaults to an empty set when omitted and is empty when the component carries no allergens. At the moment a component is created the system snapshots whether its owning customer currently has `owns_components` set to true and records the result on the component's `customer_owned` flag; that snapshot, taken at create time, is what later decides whether the component participates in customer-owned reconciliation, and it does not change if the customer's flag is edited afterward.

Each component also exposes two computed inventory figures. The `on_hand_qty` is the quantity drawable for future runs, and the `reserved_qty` is the quantity earmarked by scheduled runs that have not yet started. Both are recomputed on every event that affects them. The on-hand figure has a precise meaning: it is the sum of the `remaining_qty` of every physical lot of the component whose `status` is `AVAILABLE`, less the component's `reserved_qty`, rounded half up to three decimals. This is the *available* view. A second, traceability-only view — *physical* on hand — sums the `remaining_qty` of every lot whose status is `AVAILABLE` or `QUARANTINED` and ignores reservations entirely; it diverges from the available view exactly when one of the component's lots has been quarantined. The figure stored and returned as the component's `on_hand_qty` is always the available view.

Physical stock arrives as lots. A `Receiver` receives a lot against a component by supplying the `supplier_lot_code` as printed by the supplier, the `received_qty` in the component's base units (which must be greater than zero, else `ERR_INVALID_QUANTITY`), and the lot's `expiration_date`, which must be a valid ISO instant whether it lies in the past or the future, else `ERR_INVALID_ENUM`. On receipt the lot's `remaining_qty` is set equal to its `received_qty`, the lot's `status` begins at `AVAILABLE`, and the owning component's `on_hand_qty` is recomputed immediately. Over a lot's life its `remaining_qty` is the received quantity less everything consumed against it, and it is never driven below zero. A lot's status is one of `AVAILABLE`, `DEPLETED`, or `QUARANTINED`; the transitions between these are driven entirely by run events, never by a direct client call, and are described in the run-lifecycle narratives below.

### 3.2. Recipes, Bills of Materials, and the Approval Loop

A `Scheduler` authors a recipe — a packaging project for a given customer. Creating a recipe names the owning `customer_id` and a project `name`, and fixes three packaging parameters: the `target_fill_weight_g`, the nominal grams of product per finished unit, which must be greater than zero; the `fill_tolerance_pct`, the permitted plus-or-minus deviation of a unit's weight from target before it counts as a reject, which must be greater than zero and at most 50; and the `shelf_life_days`, the whole number of days added to a pack date to compute a finished good's expiration, which must be at least 1. A violation of any of these bounds is rejected with `ERR_INVALID_QUANTITY`. A new recipe begins in `DRAFT`, and its approval lifecycle runs through `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, and the terminal `RETIRED`.

The bill of materials is built line by line while the recipe is in `DRAFT`. A `Scheduler` adds a bill-of-materials line by naming the `component_id` it draws, the `qty_per_unit` consumed per finished unit (which must be greater than zero, else `ERR_INVALID_QUANTITY`), and an optional `scrap_factor_pct`, the percentage of that component expected to be lost as waste during a run. The scrap factor defaults to zero when omitted and must be at least zero and strictly less than 100. Each line records its parent `recipe_id`. Because adding a line participates in optimistic concurrency, the request must also carry `expected_recipe_version` matching the recipe's current `version`, as specified in Section 2.7; a mismatch is rejected with `ERR_STALE_VERSION`. While the recipe is `DRAFT`, adding a line recomputes the recipe's `allergen_profile` and increments the recipe's `version` by one.

The recipe's `allergen_profile` is computed, never supplied: it is the union of the `allergens` of the components referenced by the recipe's `INGREDIENT` bill-of-materials lines (packaging and label lines do not contribute allergens to the profile), and it defaults to an empty set. It is recomputed whenever the bill of materials changes while the recipe is `DRAFT`.

Submission moves a recipe from `DRAFT` to `PENDING_APPROVAL`. A `Scheduler` may submit only a recipe currently in `DRAFT`; a submit from any other state is rejected with `ERR_INVALID_STATE`. Submission is gated on the bill of materials being complete enough to pack: the recipe must have at least one bill-of-materials line whose component `kind` is `INGREDIENT` and at least one whose `kind` is `PACKAGING`. On a valid submit, the system recomputes the `allergen_profile` from the current ingredient lines and increments the recipe's `version` by one.

Approval is a `QAInspector`'s decision and forks. From `PENDING_APPROVAL`, approving moves the recipe to `APPROVED`, which makes it eligible to back production runs, and increments its `version` by one. Rejecting, the sibling branch, moves a `PENDING_APPROVAL` recipe to `REJECTED` and increments its `version` by one — but, unlike approval, it grants no run eligibility; a rejected recipe can back no runs. Either decision requires the recipe to be in `PENDING_APPROVAL`, and an attempt from any other state is rejected with `ERR_INVALID_STATE`. A rejected recipe is not a dead end: a `Scheduler` may revise it, moving `REJECTED` back to `DRAFT`, which makes the bill-of-materials lines editable again and increments the recipe's `version` by one. This closes a cyclic loop — `REJECTED → DRAFT → PENDING_APPROVAL` and then once more to `APPROVED` or `REJECTED` — so a recipe may iterate until it passes. Revision requires the recipe to be in `REJECTED`, else `ERR_INVALID_STATE`.

Finally, a `Scheduler` may retire an approved recipe, moving `APPROVED` to the terminal `RETIRED` and incrementing the recipe's `version` by one. Retirement requires that the recipe currently be `APPROVED` and that no production run referencing it is still live — that is, no referencing run is in `SCHEDULED`, `RUNNING`, or `PENDING_QA`. A retire that violates the state precondition is rejected with `ERR_INVALID_STATE`.

### 3.3. Lines, Crews, and Scheduling a Run

A `Scheduler` defines the physical lines and the operator crews that execute production. A production line is created with a `name`, a `rated_units_per_hour` nameplate throughput that must be greater than zero, and an optional `changeover_minutes` — the base minutes needed to change the line over between runs — which defaults to 30 and must be at least zero. A line also carries a computed `current_allergen_residue`: the allergen set left behind by the most recently started run's recipe, reset to empty by a sanitation cleanout. A crew is created with a `name` and an optional `rest_buffer_minutes` — the mandatory paid rest the crew needs between two runs — which defaults to 15 minutes and must be at least zero; this buffer defines the closed-interval gap used for crew overlap detection.

Scheduling a run is the act of placing a recipe on a line with a crew at a planned time. The request names the `recipe_id`, the `line_id`, the `crew_id`, the `planned_units` (the number of finished units intended, which must be greater than zero, else `ERR_INVALID_QUANTITY`), and the `scheduled_start` instant. The referenced recipe must be `APPROVED`; scheduling against a recipe in any other state is rejected with `ERR_RECIPE_NOT_APPROVED`. The run is created in `SCHEDULED`, the initial state of a run's lifecycle, which spans `SCHEDULED`, `RUNNING`, `PENDING_QA`, and the three terminal states `RELEASED`, `QUARANTINED`, and `CANCELLED`.

At schedule time the system computes the run's `scheduled_end` and reserves the material the run will need. The end instant is derived from the run window calculation: the run takes `planned_units` divided by the line's `rated_units_per_hour` to yield a duration in hours, which converted to minutes is that figure multiplied by 60. Changeover minutes are added only when a real changeover is needed — that is, only when the line's `current_allergen_residue`, treated as a set, differs from the recipe's `allergen_profile`, also treated as a set; when the two sets are equal the run follows back-to-back with no changeover and zero changeover minutes are added. The `scheduled_end` is the `scheduled_start` advanced by the sum of the applicable changeover minutes and the run minutes, with the minutes-to-seconds conversion rounded half up so the end lands on a whole second. Because the residue is a property of the line's recent history, the projected end is line-state-dependent rather than a fixed offset.

Two collision checks guard scheduling, and they treat their intervals differently. The **line overlap** check treats a run's window as the half-open interval from its `scheduled_start` up to but not including its `scheduled_end`: the new run's half-open window must not overlap the half-open window of any non-terminal run already on the same line, where non-terminal means `SCHEDULED`, `RUNNING`, or `PENDING_QA`. Because the interval is half-open, a new run whose start equals another run's end is allowed — exact back-to-back is fine on a line. A violation is rejected with `ERR_LINE_OVERLAP`. The **crew overlap** check is stricter: it expands the run's window by the crew's `rest_buffer_minutes` on each side, forming the closed interval from `scheduled_start` minus the buffer through `scheduled_end` plus the buffer, endpoints included, and that buffered closed window must not overlap any non-terminal run already on the same crew. Because the buffered interval is closed and includes its endpoints, exact back-to-back is rejected for a crew, the opposite of the line rule. A violation is rejected with `ERR_CREW_OVERLAP`.

Reservation, the second effect of scheduling, raises each bill-of-materials component's `reserved_qty` by the quantity the run will eventually need and recomputes each affected component's `on_hand_qty`. Reservation holds material against the run until the run either starts (which converts the reservation into real consumption) or is cancelled while still scheduled (which releases it).

### 3.4. Starting a Run: Changeover, Expiry, Material, and Lot Coding

Starting a run is where most of the system's safety machinery fires. A `Scheduler` starts a run that is currently `SCHEDULED`; a start from any other state is rejected with `ERR_INVALID_STATE`. The start request carries `expected_line_version`, and the referenced recipe must still be `APPROVED`. Several preconditions are then evaluated, and their relative order matters because each carries a distinct error.

The **allergen changeover** gate fires first among the start-specific safety checks. The line's `current_allergen_residue` must not contain any allergen that is absent from the recipe's `allergen_profile`, unless a sanitation cleanout has cleared the line since its last started run. In plain terms, a line still dirty with an allergen the incoming recipe does not declare — most sharply, packing an allergen-free recipe on an allergen-contaminated line — is blocked with `ERR_ALLERGEN_CHANGEOVER_REQUIRED`, and the only way to clear the block without changing the recipe is a sanitation event on that line. Next, **lot expiry**: no physical lot selected for consumption may have an `expiration_date` at or before the logical clock at the moment of start; a chosen lot that is expired blocks the start with `ERR_LOT_EXPIRED`. Next, **material sufficiency**: for each bill-of-materials line, the aggregate `remaining_qty` of the component's available, non-expired lots must cover the run's scrap-inflated required quantity for that line; a shortfall is rejected with `ERR_INSUFFICIENT_MATERIAL`.

The required quantity per line is computed as follows. The gross draw per finished unit is the line's `qty_per_unit` inflated by its scrap factor — that is, `qty_per_unit` multiplied by one plus `scrap_factor_pct` divided by 100. The line's total required quantity is that gross-per-unit figure multiplied by the run's `planned_units`, rounded half up to three decimals. The lots that satisfy this requirement are drawn first-expired-first-out: among the component's `AVAILABLE`, non-expired lots, the system orders by `expiration_date` ascending, breaking ties by `created_at` ascending, and draws from each in turn. The quantity drawn from any one lot is the smaller of that lot's `remaining_qty` and the residual still required after earlier lots, and one `LotConsumption` record is written per lot-and-line touched, recording the `production_run_id`, the `component_lot_id`, the `bom_line_id`, and the `consumed_qty` actually drawn from that lot.

When a valid start succeeds, a cascade of effects fires atomically. The run's `pack_date` is stamped to the current logical clock, and the run transitions `SCHEDULED → RUNNING`. The lot code is minted (see below) onto the run's `lot_code`. The selected lots are consumed first-expired-first-out: the `LotConsumption` rows are created, each touched lot's `remaining_qty` is decremented by the quantity drawn, and any lot whose `remaining_qty` reaches zero moves `AVAILABLE → DEPLETED` and is no longer selectable for future runs. Each consumed component's `on_hand_qty` is recomputed and the `reserved_qty` this run had been holding is released. The line's `current_allergen_residue` is set to the recipe's `allergen_profile`, and because this mutates the line, the line's `version` is incremented by one — the same version the start's `expected_line_version` was checked against. For every consumed component that is customer-owned, a ledger entry is emitted with `reason` `CONSUME` and a `delta_qty` equal to the negative of the consumed quantity, recording the `customer_id`, the `component_id`, and the `production_run_id`; each such entry also snapshots the component's customer-owned status on its own `customer_owned` flag at consumption time. Finally the run's `version` is incremented by one.

The `lot_code` is a deterministic, human-readable string minted at start. The pack date is formatted as an eight-digit year-month-day. The run's sequence number within that customer and pack day is one plus the count of other production runs of the same customer whose pack date falls on the same day and that have already reached or passed running — that is, other runs whose `status` is `RUNNING`, `PENDING_QA`, `RELEASED`, or `QUARANTINED`, excluding the run being started itself. The lot code is then assembled as the customer's `code`, a hyphen, the eight-digit pack date, a hyphen, a four-character recipe short token, a hyphen, and the sequence zero-padded to three digits. The recipe short token is the first four alphanumeric characters of the recipe's `name` uppercased, padded with the letter X if the name has fewer than four alphanumeric characters.

### 3.5. Completing a Run, Run Rate, and Waste

Once packing is done, a `Scheduler` completes a `RUNNING` run; a complete from any other state is rejected with `ERR_INVALID_STATE`. The complete request reports the `actual_units_good` and `actual_units_scrapped` produced, each defaulting to zero. The two together — the total produced, good plus scrapped — must not exceed the over-run ceiling, which is `planned_units` multiplied by one plus the over-run allowance of 10 percent (so a run planned for some number of units may produce at most that number times 1.10); exceeding the ceiling is rejected with `ERR_OVERRUN_EXCEEDED`. A valid complete stores the two actual figures, computes the run's realized throughput, emits scrap-waste reconciliation entries for customer-owned material, transitions the run `RUNNING → PENDING_QA`, and increments the run's `version` by one.

The realized throughput, recorded as `run_rate_units_per_hour`, is the total produced units divided by the elapsed hours. Elapsed hours is the logical clock at completion minus the run's `pack_date`, expressed as a floating-point number of hours, and total units is `actual_units_good` plus `actual_units_scrapped`. As a boundary case, when elapsed hours is exactly zero — a run completed at the same clock instant it started — the rate is defined to be zero rather than a division by zero. Otherwise the rate is the total divided by elapsed hours, rounded half up to two decimals.

Waste is the material drawn that did not end up in good finished units, and it is measured two ways. The **planned** waste for a bill-of-materials line is the line's scrap-inflated required quantity at start less the unscrapped need — that is, the required quantity computed in Section 3.4 minus the product of `qty_per_unit` and `planned_units`; it reflects only the scrap reserved by the scrap factor and ignores actual output. The **actual** waste for a line is the total actually consumed against that line — the sum of `consumed_qty` across the line's `LotConsumption` rows — minus the material embodied in the good units actually made, namely `qty_per_unit` multiplied by `actual_units_good`, rounded half up to three decimals. The two diverge whenever the actual good output differs from the planned units. At completion, for each customer-owned consumed component, a ledger entry is emitted with `reason` `SCRAP_WASTE` carrying that component's actual waste share.

A run's summary read exposes the run's `lot_code`, its `run_rate_units_per_hour`, the checkweigher `reject_rate`, and two waste totals, `planned_waste_total` and `actual_waste_total`. Both totals follow a pinned rounding order: each per-line waste figure is rounded half up to three decimals *first*, and the already-rounded per-line figures are then summed — round per line, then sum, never sum then round, and the resulting sum is not rounded again. The planned total sums the rounded planned waste across every bill-of-materials line of the run's recipe; the actual total sums the rounded actual waste across every line that has lot consumptions.

### 3.6. Quality Control: Checkweighing, Release, and Quarantine

Quality control runs on sampled fill weights. A `QAInspector` records a checkweigher reading against a run by supplying the `measured_weight_g`, the scale reading for one sampled finished unit in grams, which must be greater than zero, else `ERR_INVALID_QUANTITY`. A sample may be recorded only while the run is `RUNNING` or `PENDING_QA`; recording against a run in any other state is rejected with `ERR_RECIPE_NOT_APPROVED`. Each sample records its parent `production_run_id` and is assigned a computed `verdict` of `PASS`, `UNDER`, or `OVER` against the recipe's tolerance band. The band's lower endpoint is the recipe's `target_fill_weight_g` multiplied by one minus `fill_tolerance_pct` divided by 100, and the upper endpoint is the target multiplied by one plus `fill_tolerance_pct` divided by 100, each rounded half up to three decimals. A reading strictly below the lower endpoint is `UNDER`; a reading strictly above the upper endpoint is `OVER`; a reading anywhere from the lower endpoint through the upper endpoint inclusive — the boundaries themselves pass — is `PASS`.

Release is the quality pass branch. A `QAInspector` releases a `PENDING_QA` run; a release from any other state is rejected with `ERR_INVALID_STATE`. Release is gated by the QA reject-rate gate: the run must have at least one checkweigh sample, and its reject rate must not exceed the maximum reject rate of 0.05. The reject rate is the count of samples whose verdict is `UNDER` or `OVER` divided by the total sample count, rounded half up to four decimals; because at least one sample is required, the division is always defined. A release attempted with no samples, or with a reject rate above the maximum, is rejected with `ERR_QA_REJECT_RATE_EXCEEDED`. On a valid release the run's `fg_expiration_date` is computed as the `pack_date` plus the recipe's `shelf_life_days`, the run transitions `PENDING_QA → RELEASED` so its finished goods become sellable, and the run's `version` is incremented by one.

Quarantine is the quality fail branch and carries a divergent effect set. A `QAInspector` quarantines a `PENDING_QA` run; from any other state the request is rejected with `ERR_INVALID_STATE`. On quarantine, every component lot consumed by the run moves to `QUARANTINED` (an `AVAILABLE` lot moves `AVAILABLE → QUARANTINED`, and a fully-drawn lot moves `DEPLETED → QUARANTINED` for traceability), their remaining quantities are held out of the available on-hand computation, each affected component's `on_hand_qty` is recomputed excluding the quarantined lots, and the run's `version` is incremented by one. Unlike release, quarantine computes no finished-goods expiration and produces no sellable goods — it locks the source lots instead.

### 3.7. Cancelling a Run and Customer-Owned Reconciliation

Cancellation behaves differently depending on how far the run has progressed, and a `Scheduler` performs it. A run still in `SCHEDULED` has consumed nothing — only reservations are outstanding — so cancelling it releases the `reserved_qty` held against every bill-of-materials component and recomputes each affected component's `on_hand_qty`, then moves the run `SCHEDULED → CANCELLED` and increments its `version` by one. A run in `RUNNING` has already drawn material, so its cancellation is a full compensation: every `LotConsumption` is reversed by restoring its `consumed_qty` to the corresponding lot's `remaining_qty`, any lot that had gone `DEPLETED` flips back `DEPLETED → AVAILABLE` once its remaining quantity rises above zero, each affected component's `on_hand_qty` is recomputed, and the run moves `RUNNING → CANCELLED` with its `version` incremented by one. Cancellation is defined only from `SCHEDULED` or `RUNNING`; attempting it from any other state is rejected with `ERR_INVALID_STATE`.

The customer-owned ledger ties these effects together. Every ledger entry records the owning `customer_id`, the affected `component_id`, the emitting `production_run_id`, a signed `delta_qty`, and a `reason` of `CONSUME`, `SCRAP_WASTE`, or `RETURN_ON_CANCEL`. A start emits `CONSUME` entries with negative deltas as material is drawn; a complete emits `SCRAP_WASTE` entries for the waste share. When a `RUNNING` run is cancelled, the compensation also emits, for each customer-owned consumed component, a `RETURN_ON_CANCEL` entry whose `delta_qty` is the positive of the consumed quantity, so that the running cancel restores exactly the material it drew and the customer's reconciled balance for each component nets back to zero. A sanitation event, recorded separately by a `QAInspector` on a line, snapshots the line's `current_allergen_residue` onto its own `cleared_allergens`, records the cleaned `line_id`, empties the line's residue, and increments the line's `version` by one.

### 3.8. Validation Order

When several checks could fire on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: missing or unknown headers yield `ERR_UNAUTHENTICATED`. Authorization is next: a recognized but unpermitted role yields `ERR_UNAUTHORIZED`. Path existence follows, validated left to right, yielding `ERR_NOT_FOUND` at the first missing identifier. Then comes request well-formedness on write endpoints — a present, JSON-parseable body carrying the required fields of the correct type, else `ERR_INVALID_REQUEST`. Resource-uniqueness checks follow for the relevant creates (`ERR_DUPLICATE_CODE` for a customer code, `ERR_DUPLICATE_SKU` for a component SKU within its customer). Body foreign-key existence is then confirmed (`ERR_NOT_FOUND`). Quantity and range bounds are checked next (`ERR_INVALID_QUANTITY` for the weight, tolerance, shelf-life, and quantity fields), followed by enum validity (`ERR_INVALID_ENUM` for `kind` and for a malformed lot expiration instant).

For state-transition endpoints the state precondition is checked before the transition-specific business rules: a transition requested from a state in which it is undefined yields `ERR_INVALID_STATE`. On run start specifically, the order of the transition-specific checks is allergen changeover (`ERR_ALLERGEN_CHANGEOVER_REQUIRED`) first, then expired lots (`ERR_LOT_EXPIRED`), then material sufficiency (`ERR_INSUFFICIENT_MATERIAL`). The over-run ceiling (`ERR_OVERRUN_EXCEEDED`) guards completion. Line overlap (`ERR_LINE_OVERLAP`) and crew overlap (`ERR_CREW_OVERLAP`) guard scheduling. The QA reject-rate gate (`ERR_QA_REJECT_RATE_EXCEEDED`) guards release. The stale-version check (`ERR_STALE_VERSION`) guards run start and bom-line add. The recipe-approval and sampling-window check (`ERR_RECIPE_NOT_APPROVED`) guards run scheduling and sample recording.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that fetch a resource, list resources, drive a state transition on an existing resource, or set the logical clock return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/copack/customers` | Register a brand-owner customer | Receiver |
| GET | `/copack/customers/{id}` | Fetch a customer | Receiver, Scheduler, QAInspector |
| GET | `/copack/customers` | List customers | Receiver, Scheduler, QAInspector |
| POST | `/copack/components` | Create a component owned by a customer | Receiver |
| GET | `/copack/components/{id}` | Fetch a component including on-hand and reserved quantities | Receiver, Scheduler, QAInspector |
| GET | `/copack/components` | List components; filter by `customer_id` | Receiver, Scheduler, QAInspector |
| POST | `/copack/components/{id}/lots` | Receive a physical lot of a component into inventory | Receiver |
| GET | `/copack/components/{id}/lots` | List lots of a component | Receiver, Scheduler, QAInspector |
| GET | `/copack/component-lots/{id}` | Fetch one component lot | Receiver, Scheduler, QAInspector |
| POST | `/copack/recipes` | Create a DRAFT recipe for a customer | Scheduler |
| GET | `/copack/recipes/{id}` | Fetch a recipe including its allergen profile | Receiver, Scheduler, QAInspector |
| GET | `/copack/recipes` | List recipes; filter by `customer_id` | Receiver, Scheduler, QAInspector |
| POST | `/copack/recipes/{id}/bom-lines` | Add a BOM line to a DRAFT recipe | Scheduler |
| GET | `/copack/recipes/{id}/bom-lines` | List BOM lines of a recipe | Receiver, Scheduler, QAInspector |
| GET | `/copack/bom-lines/{id}` | Fetch one BOM line | Receiver, Scheduler, QAInspector |
| GET | `/copack/bom-lines` | List BOM lines; filter by `component_id` or `recipe_id` | Receiver, Scheduler, QAInspector |
| POST | `/copack/recipes/{id}/submit` | Submit a DRAFT recipe for approval | Scheduler |
| POST | `/copack/recipes/{id}/approve` | Approve a PENDING_APPROVAL recipe | QAInspector |
| POST | `/copack/recipes/{id}/reject` | Reject a PENDING_APPROVAL recipe | QAInspector |
| POST | `/copack/recipes/{id}/revise` | Move a REJECTED recipe back to DRAFT | Scheduler |
| POST | `/copack/recipes/{id}/retire` | Retire an APPROVED recipe with no live runs | Scheduler |
| POST | `/copack/production-lines` | Create a production line | Scheduler |
| GET | `/copack/production-lines/{id}` | Fetch a line including its allergen residue | Receiver, Scheduler, QAInspector |
| GET | `/copack/production-lines` | List lines | Receiver, Scheduler, QAInspector |
| POST | `/copack/production-lines/{id}/sanitation-events` | Record a sanitation cleanout clearing the line's allergen residue | QAInspector |
| GET | `/copack/production-lines/{id}/sanitation-events` | List a line's sanitation events | Receiver, Scheduler, QAInspector |
| POST | `/copack/crews` | Create an operator crew | Scheduler |
| GET | `/copack/crews/{id}` | Fetch a crew | Receiver, Scheduler, QAInspector |
| GET | `/copack/crews` | List crews | Receiver, Scheduler, QAInspector |
| POST | `/copack/production-runs` | Schedule a run on a line and crew against an APPROVED recipe | Scheduler |
| GET | `/copack/production-runs/{id}` | Fetch a run including lot code, run rate, and finished-goods expiration | Receiver, Scheduler, QAInspector |
| GET | `/copack/production-runs` | List runs; filter by `recipe_id`, `line_id`, `crew_id`, or `status` | Receiver, Scheduler, QAInspector |
| GET | `/copack/production-runs/{id}/summary` | Computed read: lot code, run rate, reject rate, planned vs actual waste | Receiver, Scheduler, QAInspector |
| POST | `/copack/production-runs/{id}/start` | Start a run: changeover, expiry, and material checks, FEFO consumption, lot coding | Scheduler |
| POST | `/copack/production-runs/{id}/complete` | Complete a RUNNING run: record output, compute run rate, emit scrap-waste entries | Scheduler |
| POST | `/copack/production-runs/{id}/checkweigh-samples` | Record one checkweigher reading; verdict computed | QAInspector |
| GET | `/copack/production-runs/{id}/checkweigh-samples` | List checkweigh samples for a run | Receiver, Scheduler, QAInspector |
| POST | `/copack/production-runs/{id}/release` | Release a PENDING_QA run; compute finished-goods expiration; gated on reject rate | QAInspector |
| POST | `/copack/production-runs/{id}/quarantine` | Quarantine a PENDING_QA run; lock consumed lots | QAInspector |
| POST | `/copack/production-runs/{id}/cancel` | Cancel a SCHEDULED or RUNNING run | Scheduler |
| GET | `/copack/production-runs/{id}/lot-consumptions` | List lot consumptions for a run | Receiver, Scheduler, QAInspector |
| GET | `/copack/lot-consumptions/{id}` | Fetch one lot consumption | Receiver, Scheduler, QAInspector |
| GET | `/copack/lot-consumptions` | List lot consumptions; filter by `component_lot_id` or `bom_line_id` | Receiver, Scheduler, QAInspector |
| GET | `/copack/cmr-ledger-entries/{id}` | Fetch one CMR ledger entry | Receiver, Scheduler, QAInspector |
| GET | `/copack/cmr-ledger-entries` | CMR ledger; filter by `customer_id`, `component_id`, or `production_run_id` | Receiver, Scheduler, QAInspector |
| POST | `/copack/_clock/set_current_utc` | Set the server logical clock | Receiver, Scheduler, QAInspector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_INVALID_QUANTITY` | 422 Unprocessable Entity |
| `ERR_INVALID_ENUM` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RECIPE_NOT_APPROVED` | 409 Conflict |
| `ERR_ALLERGEN_CHANGEOVER_REQUIRED` | 409 Conflict |
| `ERR_LOT_EXPIRED` | 409 Conflict |
| `ERR_INSUFFICIENT_MATERIAL` | 409 Conflict |
| `ERR_OVERRUN_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LINE_OVERLAP` | 409 Conflict |
| `ERR_CREW_OVERLAP` | 409 Conflict |
| `ERR_QA_REJECT_RATE_EXCEEDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
