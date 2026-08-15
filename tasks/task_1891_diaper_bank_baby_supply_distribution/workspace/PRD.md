# Diaper Bank Distribution API — Product Requirements Document

## 1. Introduction

A member of the National Diaper Bank Network runs the opposite of a retail shelf: product arrives unpredictably through community donation drives and wholesale purchasing, leaves in carefully sized handfuls at neighborhood distribution events, and must be accounted for twice — once as physical warehouse stock and once as restricted grant money. Between those two ledgers sit a network of partner agencies with limited on-site storage, a monthly allocation process that must divide finite per-size diaper pools fairly, and a client population whose dignity depends on never having a name or address stored anywhere in the system.

This document specifies the API that operates that diaper bank end to end. It governs the partner agency network and its monthly allocation runs, the full intake lifecycle for donations and purchases, wholesale purchasing against grant-restricted funds under segregation of duties, distribution event scheduling with household issuance gating, warehouse volunteer shift coordination, size-mix forecasting against the donation mix, and impact reporting back to funders. The consistency model is immediate: every mutation is atomically visible in its own response, and every derived counter described in this document is reconciled in the same request that invalidates it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven roles: `BankAdmin` (diaper bank operations administrator: agency network, allocation runs, distribution events, and the logical clock), `WarehouseManager` (warehouse operator: inventory initialization and adjustment, donation intake, wholesale purchase order creation and receipt), `FinanceManager` (grant and funding steward: grant lifecycle, purchase order submission, funder reporting), `AgencyCoordinator` (staff of a partner agency, managing that agency's own distribution events and issuances), `PrivacyOfficer` (client-data steward under the dignity policy), `VolunteerCoordinator` (warehouse volunteer scheduler), and `Volunteer` (an unpersisted identity who self-signs up by email). A request with missing headers, or whose `X-User-Role` is not one of these seven declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed for the endpoint it targets is rejected with `ERR_FORBIDDEN_ROLE`.

Role identity works in two distinct ways. When `X-User-Role` is `AgencyCoordinator`, `X-User-ID` is the `id` of the acting PartnerAgency; ownership checks on any resource that references a PartnerAgency — a distribution event through its `host_agency_id`, an allocation line through its `agency_id`, an issuance through the event that owns it — compare that foreign-key field to `X-User-ID`, and a coordinator touching another agency's resource is rejected with `ERR_FORBIDDEN_ROLE`. For the remaining six roles — `BankAdmin`, `WarehouseManager`, `FinanceManager`, `PrivacyOfficer`, `VolunteerCoordinator`, and `Volunteer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where an actor trail is required (for example as `created_by_user_id` or `submitted_by_user_id` on a purchase order) or capture the role header (as `recorded_by_role` on an issuance), but it never compares the header value to any entity's `id`.

Client data is walled off by policy, not just by convention: household registration, household reads and updates, eligibility decisions, and household issuance history are `PrivacyOfficer`-only operations, and the denial explicitly includes `BankAdmin` — an administrator who attempts to touch a household record receives `ERR_FORBIDDEN_ROLE` like anyone else.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. One listing overrides this default: the lines of an allocation run are sorted by size code first, as described in §3.4.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

A single logical clock governs every time-derived behavior in the system: event scheduling windows, the calendar-month checks on allocation run periods, the forecast and donation-mix windows, household monthly allotment accounting, and every system-stamped timestamp — `posted_at`, `fulfilled_at`, `published_at`, `computed_at`, `completed_at`, `signed_up_at`, and `generated_at` are all taken from this clock. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time.

A `BankAdmin`-only, test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Setting the clock rebases every clock-derived window described in this document — trailing windows, calendar months, and event end checks all follow the new reading.

### 2.5. Common Resource Properties

All resources in this system — partner agencies, grants, the inventory singleton, intake batches, purchase orders, allocation runs, allocation lines, distribution events, issuances, client households, and volunteer shifts — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, updated upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource.

Recomputation of a derived field is a mutation like any other: when an operation described in §3 updates a computed counter on a resource, that resource's `updated_at` refreshes and its `version` increments, even when the operation targeted a different resource. The inventory singleton in particular advances its `version` on every stock-affecting mutation anywhere in the system — intake posts, voids and recounts, physical-count adjustments, allocation publishes, retracts and finalizes, purchase receipts, and issuance fulfillments.

### 2.6. The Request Validation Pipeline

Every request is evaluated against a fixed pipeline of validation categories, in this order. First, authentication: the identity headers must be present and the role declared (§2.1). Second, authorization: the role must be listed for the endpoint, with the coordinator scoping and client-data walling rules of §2.1 applied. Third, path existence: every identifier in the URL path must resolve to an existing resource, checked strictly left to right, with the first unresolvable identifier producing `ERR_NOT_FOUND` before any later segment is examined. Fourth, state checks: the target resource's current status must admit the requested transition — this category also carries the optimistic-concurrency version check on inventory adjustments (§2.12). Fifth, safety checks: privacy restrictions, consent, household eligibility, and segregation of duties. Sixth, uniqueness and overlap constraints. Seventh, temporal rules. Eighth, referential rules. Ninth, fiscal rules — and within the fiscal category the declared evaluation order is grant restriction first, then grant budget, then allocation existence, then allocation sufficiency, then stock sufficiency, then household allotment. Tenth and last, request-body validation: malformed fields, bad enumerations, unknown size codes, an `ends_at` that does not fall after `starts_at`, empty line arrays, quantities below one, unresolvable foreign references in the body, and a second attempt to initialize the inventory are all rejected with `ERR_VALIDATION`.

### 2.7. Units, Money, and Rounding Discipline

Diapers and training pants are counted in integer units; no fractional unit exists anywhere in the system. All monetary values are integer cents. Where a calculation produces a fractional intermediate value, the rounding method is round half up, applied at the granularity each calculation declares: purchase-order line totals are rounded half up to whole cents before any summation, forecast rates are rounded half up to two decimal places, and mix shares are rounded half up to four decimal places. Division inside the allocation formula truncates instead — shares there are rounded down to whole units, as §3.4 specifies. All numeric values in API responses are represented as standard JSON numbers, never strings.

### 2.8. The Per-Size Inventory Ledger

Inventory is a singleton, created exactly once through an initialization step that establishes one ledger entry for each of the eight size codes the bank recognizes: `NEWBORN`, `SIZE_1`, `SIZE_2`, `SIZE_3`, `SIZE_4`, `SIZE_5`, `SIZE_6`, and `TRAINING_PANTS`. The `sizes` map carries, for every size code, five quantities: `on_hand_units` (physical stock), `reserved_units` (stock earmarked by published allocation runs), `reorder_threshold_units` (a per-size floor set at initialization), `available_units`, and `restock_needed`. The last two are derived and must always agree with the first three: `available_units` is `on_hand_units` minus `reserved_units`, and `restock_needed` is true exactly when `on_hand_units` is less than or equal to `reorder_threshold_units`. The singleton also exposes `initialized` (true once the initialization step has run) and `total_on_hand_units`, the sum of `on_hand_units` across all eight sizes.

### 2.9. The Reservation Model: Earmarking, Consuming, and Releasing Stock

The same per-size pool is shared by three concerns — what is physically present, what is promised to agencies, and what can still be promised — and the ledger keeps them in lockstep. Publishing an allocation run moves units from the available column into `reserved_units`; fulfilling an issuance at a distribution event debits `on_hand_units` and `reserved_units` by the same quantity, so fulfillment itself never changes `available_units`; and releasing a line — through agency suspension or run finalization — returns its unfulfilled remainder from `reserved_units` back to the available pool. Each agency's `active_allocated_units` mirrors this from the recipient side: it is the sum of allocated-but-unfulfilled units over that agency's allocation lines whose status is `ALLOCATED` or `PARTIALLY_FULFILLED`, and it is recomputed whenever those lines move.

### 2.10. Client Dignity and Data Privacy

The system stores no personally identifying information about the families it serves — no name, address, or contact fields exist on any resource. A client household is known only by a pseudonymous `household_code`, and everything about the household is reachable exclusively by the `PrivacyOfficer` (§2.1). A household flagged `privacy_restricted` carries a stricter rule: only the `PrivacyOfficer` may record supplies given to that household, even at events where an `AgencyCoordinator` would otherwise serve families. Every issuance captures `recorded_by_role`, the `X-User-Role` of whoever recorded it, as a permanent audit trail for this policy.

### 2.11. Segregation of Duties in Purchasing

Wholesale purchasing splits responsibility across two roles so that no single operator can both order and commit bank funds. A purchase order is created by a `WarehouseManager`, and the system permanently records the creator's header identity in `created_by_user_id`. Submission — the act that commits grant money — belongs to a `FinanceManager`, and the submitting identity must differ from `created_by_user_id`; an attempt by the same operator to submit their own order is rejected with `ERR_SOD_VIOLATION`. The submitter's identity is recorded in `submitted_by_user_id`. Cancellation is symmetric with authority: the `WarehouseManager` may cancel an order only while it is still a draft, while cancelling a submitted order — which releases committed funds — belongs to the `FinanceManager`.

### 2.12. Optimistic Concurrency Control

Exactly one write in the system carries an optimistic-concurrency guard: the physical-count adjustment against the inventory singleton. The adjustment request must carry `expected_inventory_version`, a non-optional field holding the client-adjusted value of the inventory's `version` as last observed. The absolute correction in the request is computed from that observed state, so if any other write — an intake post, a void, a recount, a fulfillment, a publish — has advanced the inventory's `version` since the client last read it, the request's absolute value is stale and the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing a fresh read and a recomputed correction. No other endpoint takes a version field.


## 3. Business Logic & Workflows

### 3.1. Partner Agencies and the Distribution Network

The bank does not distribute directly to families; it distributes through a network of partner agencies. A `BankAdmin` enrolls an agency by providing a display `name`, a unique short `agency_code` (a code already in use is rejected with `ERR_DUPLICATE_CODE`), a `contact_email`, and the two inputs the allocation formula consumes: `children_served_monthly`, the number of children the agency serves per month (zero or more), and `storage_capacity_units`, the agency's total on-site storage expressed in diaper units (zero or more). A newly enrolled agency starts `ACTIVE`. The agency roster can be listed by every declared role except `Volunteer` and filtered by `status`; a single agency record can be read by the bank's administrative, finance, and warehouse roles, while an `AgencyCoordinator` may read only the record whose `id` matches their own `X-User-ID`.

Enrollment values are not immutable: a `BankAdmin` may update an agency's `children_served_monthly`, `storage_capacity_units`, or `contact_email`, and each such update increments the agency's `version`. These two allocation inputs only take effect at the next formula run — changing them never rewrites lines that have already been computed.

Suspension is the network's enforcement action. When a `BankAdmin` suspends an agency, it transitions `ACTIVE` → `SUSPENDED`, and the suspension cascades through everything the agency was promised: every allocation line belonging to that agency whose status is `ALLOCATED` or `PARTIALLY_FULFILLED` transitions to `RELEASED`, with `released_units` set to the line's `allocated_units` minus its `fulfilled_units`. For each released line, the inventory's `reserved_units` for that line's `size_code` is decremented by the released amount, returning the stock to the available pool. The agency's `active_allocated_units` is recomputed — it becomes zero — and the agency's `version` increments. `SUSPENDED` is terminal, and a suspended agency's practical consequence reaches beyond allocations: an event hosted by a non-`ACTIVE` agency cannot be opened (§3.5). Both the bank and the coordinator can review an agency's allocation lines across all runs, filterable by `status`.

### 3.2. Intake: Donations, Valuation, and the Count–Post–Recount Cycle

Before any stock can move, a `WarehouseManager` initializes the inventory singleton, optionally supplying per-size `thresholds`; any size omitted from `thresholds` starts with a `reorder_threshold_units` of zero. Initialization creates all eight size entries with zero on hand and zero reserved and flips `initialized` to true. Because the singleton exists exactly once, a second initialization attempt is rejected with `ERR_VALIDATION`.

Donated product enters through an intake batch. A `WarehouseManager` records a donation with a `donor_name` and an array of `lines`, each line pairing a `size_code` with a `quantity` of one or more; the batch is born `COUNTED` with `source_type` `DONATION` and a null `purchase_order_id`. The batch's `total_units` is the sum of its line quantities. Its `valued_total_cents` prices each line at a published fair-market table — 35 cents per `NEWBORN` diaper, 32 per `SIZE_1`, 30 per `SIZE_2`, 28 per `SIZE_3`, 26 per `SIZE_4`, 24 per `SIZE_5`, 22 per `SIZE_6`, and 40 cents per `TRAINING_PANTS` unit — and sums the results. A second valuation variant exists for purchased product: batches created by receiving a purchase order carry `source_type` `PURCHASE`, reference their order through `purchase_order_id`, leave `donor_name` null, and are valued at the actual invoiced `unit_cost_cents` of the matching purchase-order line for each size, so identical quantities under the two source types generally produce different valuations. The batch ledger can be listed with `source_type`, `status`, and `purchase_order_id` filters.

Posting is the moment counted product becomes stock. A `WarehouseManager` posts a batch — `COUNTED` → `POSTED` — and each line's `quantity` is added to the inventory's `on_hand_units` for that size; the batch's `posted_at` is stamped from the logical clock, and both the batch's and the inventory's `version` increment. Posting a batch that is not `COUNTED` fails with `ERR_INVALID_BATCH_STATE`.

Counts are sometimes wrong, so the intake cycle loops. Recounting a `POSTED` batch moves it back to `COUNTED` with replacement `lines` supplied in the request: the system first verifies that every current line can be withdrawn — for each line, the size's `on_hand_units` minus the line's `quantity` must not be negative, otherwise the recount is rejected with `ERR_INSUFFICIENT_STOCK` — then withdraws each old line's contribution from `on_hand_units`, replaces the batch's `lines` with the request's, and recomputes `total_units` and `valued_total_cents`. The round trip `COUNTED` → `POSTED` → `COUNTED` → `POSTED` is a compensating pair for on-hand stock: recount withdraws, reposting redeposits. Batch and inventory versions increment on each hop.

Voiding retires a batch into the terminal `VOIDED` state, with an optional `reason`. Voiding from `COUNTED` has no inventory effect — the batch was never posted — and increments only the batch's `version`. Voiding from `POSTED` requires the same per-line stock check as a recount (a shortfall yields `ERR_INSUFFICIENT_STOCK`) and subtracts each line's `quantity` from `on_hand_units`, an exact reversal of the post transition; both versions increment. Attempting to post, recount, or void from a status without that edge is rejected with `ERR_INVALID_BATCH_STATE`.

Physical counts drift from ledger counts, and corrections are absolute rather than relative. A `WarehouseManager` records a physical-count correction by naming a `size_code`, an absolute `new_on_hand_units`, and a `reason`, and the request must carry `expected_inventory_version` as described in §2.12 — a stale value is rejected with `ERR_STALE_VERSION`. A successful adjustment sets that size's `on_hand_units` to the supplied absolute value and increments the inventory's `version`.

### 3.3. Grant Funding and Wholesale Purchasing

Grants are the money side of the double ledger. A `FinanceManager` registers a grant with a `funder_name`, a unique `grant_code` (duplicates rejected with `ERR_DUPLICATE_CODE`), the awarded `total_amount_cents` (greater than zero), the grant window's `start_date` and `end_date`, and an optional `restriction` — `UNRESTRICTED` (the default), `PRODUCT_PURCHASE_ONLY`, or `OPERATIONS_ONLY`. A grant starts `ACTIVE`. Its funds position is always derivable: `committed_cents` is the sum of `total_cost_cents` over purchase orders referencing the grant whose status is `SUBMITTED`; `spent_cents` is the same sum over orders whose status is `RECEIVED`; `DRAFT` and `CANCELLED` orders contribute to neither sum; and `available_cents` is `total_amount_cents` minus `committed_cents` minus `spent_cents`.

A `WarehouseManager` drafts a wholesale purchase order against a grant by providing the `grant_id` (which must resolve to an existing grant, else `ERR_VALIDATION`), a `vendor_name`, order `lines` of `size_code`, `quantity` (at least one), and `unit_cost_cents` (zero or more), and an optional `discount_pct` — a non-negative vendor nonprofit discount fraction less than one, defaulting to zero. The order's `total_cost_cents` is computed once, at creation, and fixed thereafter: for each line, multiply `quantity` by `unit_cost_cents` by one minus `discount_pct`, round the result half up to whole cents, and only then sum the per-line totals. The rounding order is pinned — round each line first, then sum; summing first and rounding once would produce a different cent total and is rejected. The creator's identity is recorded in `created_by_user_id`, and the order begins `DRAFT`.

Submission commits the money and is guarded by five checks evaluated in a declared order: the order must be `DRAFT` (otherwise `ERR_PO_NOT_SUBMITTABLE`), the referenced grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`), the submitter's `X-User-ID` must differ from `created_by_user_id` (otherwise `ERR_SOD_VIOLATION`, per §2.11), the grant's `restriction` must not be `OPERATIONS_ONLY` — a product purchase against an operations-only grant yields `ERR_GRANT_RESTRICTION_VIOLATION` — and finally the order's `total_cost_cents` must not exceed the grant's `available_cents` (otherwise `ERR_GRANT_BUDGET_EXCEEDED`); an exact fit, where the order consumes the grant's last available cent, is allowed. On submission the order transitions `DRAFT` → `SUBMITTED`, the grant's `committed_cents` increases by `total_cost_cents` with `available_cents` recomputed, `submitted_by_user_id` is recorded, and both the order's and the grant's `version` increment.

Receiving turns committed money into spent money and stock. A `WarehouseManager` receives a `SUBMITTED` order — any other status yields `ERR_PO_NOT_RECEIVABLE` — against a grant that must still be `ACTIVE` (`ERR_GRANT_NOT_ACTIVE`). The request carries `received_lines`, whose sizes must be exactly the set of sizes present in the order's `lines` (a mismatch is rejected with `ERR_VALIDATION`). On receipt, the grant's `committed_cents` decreases and its `spent_cents` increases by `total_cost_cents`; a new intake batch is created directly in `POSTED` status with `source_type` `PURCHASE`, the order's id as its `purchase_order_id`, and the received lines as its `lines`, adding each received quantity to the inventory's `on_hand_units`; the order's `received_intake_batch_id` points at that batch. If the grant's `spent_cents` has reached or exceeded its `total_amount_cents` after crediting — equality exhausts — the grant automatically transitions `ACTIVE` → `EXHAUSTED`. The order lands in terminal `RECEIVED`, and the versions of the order, the grant, and the inventory each increment.

Cancellation releases whatever was committed. A `WarehouseManager` may cancel an order only while it is `DRAFT` — a warehouse attempt on any other status is rejected with `ERR_PO_NOT_SUBMITTABLE` — and draft cancellation moves no funds, incrementing only the order's `version`. A `FinanceManager` cancels a `SUBMITTED` order, which decreases the grant's `committed_cents` by `total_cost_cents`, an exact reversal of submission, with `available_cents` recomputed and both versions incremented. `CANCELLED` and `RECEIVED` are terminal. The order book can be listed with `grant_id`, `status`, and `received_intake_batch_id` filters.

Closing a grant retires it. A `FinanceManager` closes an `ACTIVE` grant only when no purchase order referencing it remains `SUBMITTED`; an open submitted order blocks the close with `ERR_GRANT_HAS_OPEN_POS`. The grant transitions `ACTIVE` → `CLOSED` and its `version` increments. Draft orders referencing the grant are left in place, but they can never be submitted afterwards — submission requires an `ACTIVE` grant and will fail with `ERR_GRANT_NOT_ACTIVE`.

### 3.4. The Monthly Allocation Run

Once a month the bank divides its available stock among the agency network through an allocation run. A `BankAdmin` opens a run by naming its `period` — a calendar month in `YYYY-MM` form — and optionally a `formula_variant`, either `NEED_WEIGHTED` (the default) or `EQUAL_SPLIT`. The period must be unique across all runs (a repeat is rejected with `ERR_DUPLICATE_PERIOD`) and must not fall before the logical clock's current calendar month (a past period is rejected with `ERR_PERIOD_IN_PAST`). The run starts `DRAFT` with `computed_at` null and no lines.

Computing the run executes the allocation formula as a waterfall, per size, in a fixed agency order. The eligible set is exactly the agencies whose `status` is `ACTIVE`, sorted by `children_served_monthly` descending with ties broken by `created_at` ascending. For each of the eight size codes, the pool is that size's `available_units` at compute time — on hand minus reserved, so stock already promised by other published runs is never re-promised. The formula walks the sorted agencies, handing each a grant before moving to the next, and tracks the units still remaining in the pool. Under `NEED_WEIGHTED`, an agency's raw share is the pool multiplied by the agency's `children_served_monthly` divided by the total `children_served_monthly` across all eligible agencies, rounded down to a whole unit; when that total is zero, every raw share is zero. Under `EQUAL_SPLIT`, the raw share is the pool divided by the number of eligible agencies, rounded down — or zero when no agency is eligible; the floor, cap, and waterfall order are identical, but identical inputs produce different `allocated_units` under the two variants. A dignity floor applies in both variants: when an agency serves at least one child and its raw share falls below 100 units, the share is raised to 100, provided at least 100 units still remain in the pool. A capacity cap applies next: no agency receives more for a size than half of its `storage_capacity_units`, rounded down to a whole unit. The final grant is the smallest of the raw share, the capacity cap, and the units remaining in the pool. When that grant is positive, a line is written for the run, agency, and `size_code` with `allocated_units` set to the grant and status `PROJECTED`; a zero grant produces no line at all. Each line carries its `allocation_run_id`, `agency_id`, and `size_code`, with `fulfilled_units` and `released_units` starting at zero. Computation is only valid from `DRAFT` (otherwise `ERR_RUN_NOT_DRAFT`); recomputing discards every line the run previously produced — whatever their status — and writes a fresh set, so recomputation is idempotent and never duplicates lines. Each compute stamps `computed_at` from the logical clock and recomputes the run's `total_allocated_units`, the sum of `allocated_units` over all its lines.

Publishing makes the promises real. A `BankAdmin` publishes a run — `DRAFT` → `PUBLISHED` — only when the run is still `DRAFT` (`ERR_RUN_NOT_DRAFT`), has been computed at least once (`computed_at` non-null, otherwise `ERR_RUN_NOT_COMPUTED`), and passes a final stock gate: for each size, the sum of `allocated_units` over the run's lines must not exceed the inventory's `on_hand_units` for that size (otherwise `ERR_INSUFFICIENT_STOCK`). On publish, every `PROJECTED` line transitions to `ALLOCATED`, the inventory's `reserved_units` for each size increases by the run's total allocated for that size, `published_at` is stamped, and the versions of the run and the inventory increment.

Two exits from `PUBLISHED` exist, and both require it (any other status yields `ERR_RUN_NOT_PUBLISHED`). Retraction — `PUBLISHED` → `DRAFT` — is permitted only while no line has consumed anything: a single line with `fulfilled_units` above zero makes the run unretractable, likewise `ERR_RUN_NOT_PUBLISHED`. Retracting returns every `ALLOCATED` line to `PROJECTED`, decrements each size's `reserved_units` by the run's allocated total for that size (an exact reversal of publish), clears `published_at` back to null, and increments both versions. Finalization — `PUBLISHED` → `FINALIZED`, the terminal state — releases the leftovers: every line in `ALLOCATED` or `PARTIALLY_FULFILLED` transitions to `RELEASED` with `released_units` set to `allocated_units` minus `fulfilled_units`, the inventory's `reserved_units` is decremented by each released amount, and lines already `FULFILLED` are left unchanged.

A run can also finalize itself. Fulfillment at distribution events credits lines (§3.5): a line whose `fulfilled_units` lands between zero and `allocated_units` moves `ALLOCATED` → `PARTIALLY_FULFILLED`; a line whose `fulfilled_units` reaches `allocated_units` — whether in one crediting, jumping straight from `ALLOCATED`, or from `PARTIALLY_FULFILLED` — flips to `FULFILLED`, the equality boundary being what flips it. Each such line mutation increments the line's `version`. When the last open line of a `PUBLISHED` run reaches `FULFILLED`, the run automatically transitions to `FINALIZED` with no reservation release — every reserved unit was consumed by fulfillment — and only the run's `version` increments. The run's lines can be listed by the bank or the coordinator, sorted by `size_code` ascending, then by the agency's `children_served_monthly` descending, then by the agency's `created_at` ascending.

### 3.5. Distribution Events and Household Issuance

Distribution events are where reserved stock finally reaches families. A `BankAdmin`, or an `AgencyCoordinator` acting for their own agency, schedules an event by naming the `host_agency_id`, a `site_name`, and the window's `starts_at` and `ends_at` — the start must fall before the end, otherwise `ERR_VALIDATION`. Scheduling enforces one site's single-booking rule: the new event's half-open window, inclusive of `starts_at` and exclusive of `ends_at`, must not intersect the window of any existing event at the same `site_name` whose status is `SCHEDULED`, `OPEN`, or `LOCKED`; a conflict is rejected with `ERR_SITE_SCHEDULE_CONFLICT`, while two events that merely touch — one's `ends_at` equal to the other's `starts_at` — are allowed. The event begins `SCHEDULED`, and the events calendar can be listed with `host_agency_id`, `site_name`, and `status` filters.

Opening an event — `SCHEDULED` → `OPEN` — requires that the event is still `SCHEDULED` (otherwise `ERR_INVALID_EVENT_STATE`), that its host agency is `ACTIVE` (otherwise `ERR_AGENCY_NOT_ACTIVE`), and that the logical clock has not reached the event's `ends_at` (opening at or after the end is rejected with `ERR_EVENT_ALREADY_ENDED`). While `OPEN`, issuances may be recorded. Locking — `OPEN` → `LOCKED` — freezes recording ahead of completion; unlocking — `LOCKED` → `OPEN` — is the legal revert branch, and the lock/unlock pair may repeat. Each of these transitions increments the event's `version`, and any of them attempted from a status without that edge yields `ERR_INVALID_EVENT_STATE`.

Recording an issuance is the most heavily gated write in the system. Either an `AgencyCoordinator` (at their own agency's events only) or a `PrivacyOfficer` (anywhere) may record, supplying the `household_id` and the `lines` of `size_code` and `quantity` handed over; each quantity must be at least one, and the household must resolve, with malformed bodies rejected as `ERR_VALIDATION`. The gates fire in the pipeline order of §2.6: the event must be `OPEN` (otherwise `ERR_EVENT_NOT_OPEN`); if the household is flagged `privacy_restricted`, only a `PrivacyOfficer` may record for it (otherwise `ERR_PRIVACY_RESTRICTED`); the household's `eligibility_status` must be `ELIGIBLE` (otherwise `ERR_HOUSEHOLD_NOT_ELIGIBLE`); and each household may receive at most one issuance per event (a second attempt yields `ERR_DUPLICATE_HOUSEHOLD_ISSUANCE`). Then the fiscal chain runs per size, in order: a `PUBLISHED` allocation line must exist for the triple of the logical clock's current calendar month, the event's host agency, and the line's size (otherwise `ERR_NO_PUBLISHED_ALLOCATION`); the requested quantity must not exceed that line's unfulfilled remainder — `allocated_units` minus `fulfilled_units` (otherwise `ERR_ALLOCATION_EXCEEDED`); and the quantity must not exceed the inventory's `on_hand_units` for the size (otherwise `ERR_INSUFFICIENT_STOCK`). Finally, the requested total across all lines must fit the household's remaining monthly allotment (§3.6), otherwise `ERR_ALLOTMENT_EXCEEDED`. A recorded issuance starts `RECORDED`, linked to its event through `event_id`, with `total_units` summed over its lines and `recorded_by_role` captured for the privacy audit trail; the household's `consumed_this_month_units` is recomputed. No stock moves at record time — inventory moves only at completion.

Completion is a three-hop cascade. A `BankAdmin` or the hosting `AgencyCoordinator` completes a `LOCKED` event — `LOCKED` → `COMPLETED`, and only from `LOCKED` (otherwise `ERR_INVALID_EVENT_STATE`). In the first hop, every `RECORDED` issuance of the event transitions to `FULFILLED` with `fulfilled_at` stamped from the logical clock. In the second hop, each fulfilled issuance line debits the inventory twice — `on_hand_units` decreases by the quantity and `reserved_units` decreases by the same quantity, because the reservation is being consumed rather than released, leaving `available_units` unchanged by fulfillment itself — and the allocation line selected by the clock's current calendar month, the run's `PUBLISHED` status, the event's host agency, and the line's size is credited, its `fulfilled_units` increasing by the quantity and its status recomputed per §3.4. In the third hop, a line reaching equality flips to `FULFILLED`, and when every line of a run is `FULFILLED` the run auto-finalizes. The event stamps `completed_at`, recomputes `issued_total_units` as the sum of `total_units` over its `FULFILLED` issuances, and the versions of the event, the inventory, and every touched allocation line increment. `COMPLETED` is terminal.

Cancellation is gentler than completion. An event may be cancelled from `SCHEDULED` or from `OPEN`; a `LOCKED` event cannot be cancelled directly — it must be unlocked first — and cancellation from `LOCKED` or any action on a terminal event is rejected with `ERR_INVALID_EVENT_STATE`. Cancelling an `OPEN` event voids its work: every `RECORDED` issuance transitions to `VOIDED` with no inventory effect, because stock moves only on fulfillment. `CANCELLED` is terminal. Separately, an individual issuance can be voided by the hosting agency's `AgencyCoordinator` or by a `PrivacyOfficer` while its owning event is `OPEN` or `LOCKED` (voiding under any other event status yields `ERR_INVALID_EVENT_STATE`), optionally carrying a `reason`; an issuance that is no longer `RECORDED` cannot be voided (`ERR_INVALID_STATE`). Either way, voiding increments the issuance's `version` and recomputes the household's `consumed_this_month_units`. An event's issuances can be listed by the bank, the hosting coordinator, or the privacy officer.

### 3.6. Client Households, Eligibility, and the Monthly Allotment

Client households are pseudonymous by design (§2.10). A `PrivacyOfficer` registers a household with a unique `household_code` (duplicates rejected with `ERR_DUPLICATE_CODE`), a `children_sizes` array holding one size code per child in diapers — at least one and at most eight entries — and two optional flags: `consent_on_file` (a signed service consent exists, defaulting to false) and `privacy_restricted` (defaulting to false). A new household's `eligibility_status` is `PENDING_REVIEW` and its `eligibility_reason` is null. The household's `monthly_allotment_units` is 50 units per child per month — the allotment is fifty times the number of entries in `children_sizes`.

The same update operation maintains the record and drives the eligibility state machine. A `PrivacyOfficer` may revise `children_sizes` — which recomputes `monthly_allotment_units` — along with `consent_on_file` and `privacy_restricted`, and may request an eligibility decision by supplying `eligibility_status` with a free-text `eligibility_reason` that is stored with the decision. Four edges are legal: `PENDING_REVIEW` → `ELIGIBLE` and `INELIGIBLE` → `ELIGIBLE`, each requiring `consent_on_file` to be true (a decision without consent is rejected with `ERR_CONSENT_REQUIRED`); `PENDING_REVIEW` → `INELIGIBLE`; and `ELIGIBLE` → `INELIGIBLE`. The cycle is deliberate — eligibility re-determination loops between `ELIGIBLE` and `INELIGIBLE` are legal — and any transition outside these four edges is rejected with `ERR_INVALID_HOUSEHOLD_STATE`. Every update increments the household's `version`.

The monthly allotment is the household-side budget behind the final issuance gate of §3.5. Consumption is measured against the logical clock's current UTC calendar month: `consumed_this_month_units` is the sum of `total_units` over the household's `FULFILLED` issuances whose `fulfilled_at` falls in that month, plus the sum over `RECORDED` issuances whose `created_at` falls in that month; `VOIDED` issuances are excluded entirely. The household's remaining allotment is `monthly_allotment_units` minus that consumption, and an issuance whose requested total exceeds the remainder is rejected with `ERR_ALLOTMENT_EXCEEDED` — a request exactly equal to the remainder is allowed, and one unit above it is not. Household records and a household's issuance history (filterable by `status`) are readable by the `PrivacyOfficer` alone; even a `BankAdmin` is turned away with `ERR_FORBIDDEN_ROLE`.

### 3.7. Warehouse Volunteer Shifts

Volunteer labor keeps the warehouse sorting. A `VolunteerCoordinator` creates a shift with a `title`, a `starts_at` and `ends_at` (the start must precede the end), and a `capacity` of at least one volunteer. Shift status is never set by hand: it is `OPEN` until the number of signups reaches `capacity`, at which point it becomes `FULL` — the equality boundary is what fills it — and it returns to `OPEN` the moment a withdrawal drops the count below capacity again. The shift's `signups` array holds one entry per volunteer — `volunteer_email`, `volunteer_name`, and a clock-stamped `signed_up_at` — and `signup_count` is its length.

Signing up, open to a `Volunteer` self-identifying by email or to the `VolunteerCoordinator`, appends to `signups`. Three rules guard the append: the same `volunteer_email` may appear at most once on a given shift (`ERR_DUPLICATE_SIGNUP`); a `FULL` shift accepts no further signups (`ERR_SHIFT_FULL`); and a volunteer may not hold two near-simultaneous commitments — a signup is rejected with `ERR_SHIFT_OVERLAP` when the same `volunteer_email` already appears on another shift whose window, expanded by thirty minutes on both sides, intersects the target shift's window, while an exactly-thirty-minute gap between the two windows is allowed. Withdrawal removes the matching `volunteer_email` entry. Every signup and withdrawal increments the shift's `version` and re-derives its status.

### 3.8. Forecasting and Funder Impact Reporting

Two read-side calculations close the loop between what the bank receives and what it distributes. The size-mix forecast, available to `WarehouseManager` and `BankAdmin`, takes an optional `variant` and answers with the `variant` used, a clock-stamped `generated_at`, and a per-size array under `sizes`. The default `TRAILING_ACTUAL` variant is backward-looking: over the trailing window from twenty-eight days before the logical clock through now, inclusive at both ends, each size's `weekly_rate` is the total fulfilled issuance quantity for that size in the window divided by four, and `forecast_4wk_units` is that weekly rate multiplied by four, rounded half up to a whole unit. Its `weeks_of_supply` is the size's `on_hand_units` divided by the weekly rate, rounded half up to two decimal places — or null when the trailing rate is zero. The `BOOKED_PIPELINE` variant is forward-looking committed demand instead: `forecast_4wk_units` is the sum of `allocated_units` minus `fulfilled_units` over the size's lines belonging to `PUBLISHED` runs, plus the sum of quantities over `RECORDED` issuance lines for the size at events that are `OPEN` or `LOCKED`, and its `weeks_of_supply` is always null — identical inventory and history produce different numbers under the two variants.

Both variants share the mix analysis. A size's `need_share` is its `forecast_4wk_units` divided by the sum of `forecast_4wk_units` across all sizes; when that denominator is zero, every size's `need_share` is zero. The donation window runs from ninety days before the logical clock through now, inclusive, over `posted_at` of `POSTED` batches with `source_type` `DONATION`: a size's `donation_share` is its posted donation units in the window divided by the total posted donation units in the window, or zero when the window contains no posted donations. A size's `mix_gap` is its `need_share` minus its `donation_share`, rounded half up to four decimal places — the single number that tells the bank which sizes the community donates too much of and which it must buy.

The impact report, available to `FinanceManager` and `BankAdmin`, answers a funder's question for one grant and one month. The `period` parameter names a calendar month in `YYYY-MM` form and defaults to the logical clock's current month; the reporting window runs from the first instant of the period up to but not including the first instant of the following month. Within that window: `purchased_units` sums the `total_units` of `POSTED` purchase batches whose order's `grant_id` is this grant, by their `posted_at`; `diapers_distributed_units` sums `total_units` over all `FULFILLED` issuances with `fulfilled_at` in the window — distribution is not grant-attributed, so issuances funded by any source count; `households_served` counts the distinct households among those issuances; `agencies_served` counts the distinct host agencies of their events; and `spent_cents` with `remaining_cents` mirror the grant's funds ledger of §3.3, `remaining_cents` being the grant's `available_cents`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — or append a new entry to a resource's collection, such as a volunteer signup — return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or perform a read return `200 OK`. Request and response payloads are governed by the narratives of §3; this table is deliberately minimal.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc` | Set the logical clock (test-driving) | BankAdmin |
| POST   | `/partner-agencies` | Create a partner agency | BankAdmin |
| GET    | `/partner-agencies` | List partner agencies | BankAdmin, FinanceManager, WarehouseManager, AgencyCoordinator, PrivacyOfficer, VolunteerCoordinator |
| GET    | `/partner-agencies/{id}` | Read one partner agency | BankAdmin, FinanceManager, WarehouseManager, AgencyCoordinator |
| PATCH  | `/partner-agencies/{id}` | Update an agency's allocation inputs | BankAdmin |
| POST   | `/partner-agencies/{id}/suspend` | Suspend an agency and release its allocations | BankAdmin |
| GET    | `/partner-agencies/{id}/allocation-lines` | List an agency's allocation lines across runs | BankAdmin, AgencyCoordinator |
| POST   | `/grants` | Create a grant | FinanceManager |
| GET    | `/grants/{id}` | Read one grant with its funds ledger | FinanceManager, BankAdmin, WarehouseManager |
| POST   | `/grants/{id}/close` | Close a grant | FinanceManager |
| GET    | `/grants/{id}/impact-report` | Funder impact metrics for a period | FinanceManager, BankAdmin |
| POST   | `/inventory/initialize` | Initialize the inventory singleton | WarehouseManager |
| GET    | `/inventory` | Read the inventory singleton | WarehouseManager, BankAdmin, FinanceManager |
| POST   | `/inventory/adjustments` | Record an absolute physical-count correction | WarehouseManager |
| GET    | `/inventory/forecast` | Per-size forecast, weeks of supply, donation-mix gap | WarehouseManager, BankAdmin |
| POST   | `/intake-batches` | Create a donation intake batch | WarehouseManager |
| GET    | `/intake-batches` | List intake batches | WarehouseManager, BankAdmin, FinanceManager |
| GET    | `/intake-batches/{id}` | Read one intake batch | WarehouseManager, BankAdmin, FinanceManager |
| POST   | `/intake-batches/{id}/post` | Post a counted batch into stock | WarehouseManager |
| POST   | `/intake-batches/{id}/recount` | Withdraw and replace a posted batch's lines | WarehouseManager |
| POST   | `/intake-batches/{id}/void` | Void an intake batch | WarehouseManager |
| POST   | `/purchase-orders` | Create a wholesale purchase order in draft | WarehouseManager |
| GET    | `/purchase-orders` | List purchase orders | WarehouseManager, FinanceManager, BankAdmin |
| GET    | `/purchase-orders/{id}` | Read one purchase order | WarehouseManager, FinanceManager, BankAdmin |
| POST   | `/purchase-orders/{id}/submit` | Submit a draft order and commit grant funds | FinanceManager |
| POST   | `/purchase-orders/{id}/receive` | Receive a submitted order into stock | WarehouseManager |
| POST   | `/purchase-orders/{id}/cancel` | Cancel a draft or submitted order | WarehouseManager, FinanceManager |
| POST   | `/allocation-runs` | Create a monthly allocation run | BankAdmin |
| GET    | `/allocation-runs/{id}` | Read one allocation run | BankAdmin, AgencyCoordinator |
| GET    | `/allocation-runs/{id}/lines` | List a run's allocation lines | BankAdmin, AgencyCoordinator |
| POST   | `/allocation-runs/{id}/compute` | Run the allocation formula over the draft | BankAdmin |
| POST   | `/allocation-runs/{id}/publish` | Publish a computed run and reserve stock | BankAdmin |
| POST   | `/allocation-runs/{id}/finalize` | Finalize a published run and release remainders | BankAdmin |
| POST   | `/allocation-runs/{id}/retract` | Retract an unconsumed published run | BankAdmin |
| POST   | `/distribution-events` | Schedule a distribution event | BankAdmin, AgencyCoordinator |
| GET    | `/distribution-events` | List distribution events | BankAdmin, AgencyCoordinator, WarehouseManager |
| GET    | `/distribution-events/{id}` | Read one distribution event | BankAdmin, AgencyCoordinator, WarehouseManager |
| POST   | `/distribution-events/{id}/open` | Open an event for issuance recording | BankAdmin, AgencyCoordinator |
| POST   | `/distribution-events/{id}/lock` | Lock an open event | BankAdmin, AgencyCoordinator |
| POST   | `/distribution-events/{id}/unlock` | Reopen a locked event | BankAdmin, AgencyCoordinator |
| POST   | `/distribution-events/{id}/complete` | Complete a locked event and fulfill its issuances | BankAdmin, AgencyCoordinator |
| POST   | `/distribution-events/{id}/cancel` | Cancel a scheduled or open event | BankAdmin, AgencyCoordinator |
| POST   | `/distribution-events/{id}/issuances` | Record supplies given to a household | AgencyCoordinator, PrivacyOfficer |
| GET    | `/distribution-events/{id}/issuances` | List issuances recorded at an event | BankAdmin, AgencyCoordinator, PrivacyOfficer |
| POST   | `/issuances/{id}/void` | Void a recorded issuance | AgencyCoordinator, PrivacyOfficer |
| POST   | `/households` | Register a pseudonymous client household | PrivacyOfficer |
| GET    | `/households/{id}` | Read one client household | PrivacyOfficer |
| PATCH  | `/households/{id}` | Update household details or eligibility | PrivacyOfficer |
| GET    | `/households/{id}/issuances` | List a household's issuance history | PrivacyOfficer |
| POST   | `/volunteer-shifts` | Create a warehouse volunteer shift | VolunteerCoordinator |
| POST   | `/volunteer-shifts/{id}/signups` | Sign a volunteer up for a shift | Volunteer, VolunteerCoordinator |
| POST   | `/volunteer-shifts/{id}/withdraw` | Withdraw a volunteer signup | Volunteer, VolunteerCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them (§2 and §3); this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_AGENCY_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_BATCH_STATE` | 409 Conflict |
| `ERR_PO_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_PO_NOT_RECEIVABLE` | 409 Conflict |
| `ERR_INVALID_EVENT_STATE` | 409 Conflict |
| `ERR_EVENT_NOT_OPEN` | 409 Conflict |
| `ERR_RUN_NOT_DRAFT` | 409 Conflict |
| `ERR_RUN_NOT_COMPUTED` | 409 Conflict |
| `ERR_RUN_NOT_PUBLISHED` | 409 Conflict |
| `ERR_GRANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_HOUSEHOLD_STATE` | 409 Conflict |
| `ERR_PRIVACY_RESTRICTED` | 403 Forbidden |
| `ERR_CONSENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_HOUSEHOLD_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_SITE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_SHIFT_FULL` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_PERIOD` | 409 Conflict |
| `ERR_DUPLICATE_HOUSEHOLD_ISSUANCE` | 409 Conflict |
| `ERR_DUPLICATE_SIGNUP` | 409 Conflict |
| `ERR_EVENT_ALREADY_ENDED` | 422 Unprocessable Entity |
| `ERR_PERIOD_IN_PAST` | 422 Unprocessable Entity |
| `ERR_GRANT_HAS_OPEN_POS` | 409 Conflict |
| `ERR_GRANT_RESTRICTION_VIOLATION` | 422 Unprocessable Entity |
| `ERR_GRANT_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NO_PUBLISHED_ALLOCATION` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ALLOTMENT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |
