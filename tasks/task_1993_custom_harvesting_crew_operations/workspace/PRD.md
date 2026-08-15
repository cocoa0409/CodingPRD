# Custom Harvesting Crew Operations API — Product Requirements Document

## 1. Introduction

Every summer, a custom harvesting crew works its way up the Great Plains — starting in Texas wheat in May and finishing in North Dakota by October — cutting grain for dozens of growers who contract by the acre or by the bushel. The operator owns the combines, grain carts, and trucks; hires a seasonal crew, many on H2A or TN visas; books motel and bunkhouse beds in towns the crew passes through; and bills each grower at the end of the season with adjustments for diesel price swings, grain moisture, and any hauling the crew performed. Today this entire operation is run from a pickup truck cab with a notebook, a calculator, and a phone. Double-booked machines, forgotten lodging beds, and hand-computed settlement sheets with moisture math done on a napkin are the norm, and disputes with growers over settlement figures consume weeks after the last truck unloads.

This document specifies a REST API, mounted under `/harvest`, that gives the operator a single system of record for an entire harvest season: acreage commitments by grower and state, a season-wide cutting route ordered by sequence, machine and crew availability, field execution through weather delays and breakdowns, elevator delivery tickets with moisture-adjusted bushels, and per-contract settlements with a pinned, auditable computation order. Four roles collaborate through the API — the business owner, the grower-facing liaison, the field crew boss, and the back-office billing clerk — each with sharply separated write permissions. The design goal is that every number on a settlement sheet can be traced back through the API to a scale ticket, a contract rate, and a published diesel baseline, so that season-end disputes shrink from weeks of phone calls to a lookup.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. Users and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the named role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly four roles, spelled exactly as follows:

- `HarvestOperator` — owns the custom-harvesting business and holds full lifecycle control over the season, machines, crew, and lodging sites. Only a `HarvestOperator` may create and activate a season, edit diesel prices, open the settlement window, close the season, register machines and lodging sites, onboard and activate or release crew members, dispatch repairs, return machines to service, skip route stops, and advance the logical clock.
- `GrowerLiaison` — negotiates acreage commitments with growers. Only a `GrowerLiaison` may create contracts under a season, commit or cancel them, create route stops, and dispute an issued settlement on a grower's behalf.
- `CrewBoss` — the field supervisor. Only a `CrewBoss` may depart for a stop, start cutting, pause for weather, resume, complete a stop, update actual acres, reserve and cancel machine assignments, report machine breakdowns, record delivery tickets, and book, check in, check out, or cancel lodging reservations.
- `BillingClerk` — the back-office settlement processor. Only a `BillingClerk` may create draft settlements, issue them, mark them paid, and resolve disputes.

All four roles share read access: any authenticated role may call any list or detail retrieval endpoint across all resource types.

All four roles have an **opaque identity**: `X-User-ID` is an opaque operator identifier not tied to any persisted entity, for every role. The server does not compare `X-User-ID` to any resource's `id` or foreign key; authorization is purely role-based. This applies individually to `HarvestOperator`, `GrowerLiaison`, `CrewBoss`, and `BillingClerk`.

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

### 2.3. Pagination

All list endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter defaults to 0. List responses are sorted by `created_at` ascending. The `meta` object of every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Change Tracking

Every resource in the system carries a common set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` field is an integer that starts at its initial value on creation and increments by 1 on every mutation of that resource. All resource kinds in this domain — seasons, contracts, route stops, machines, crew members, machine assignments, delivery tickets, settlements, lodging reservations, and lodging sites — carry this full common set.

Change tracking is load-bearing in this system, not cosmetic. Posting a delivery ticket, for example, increments the parent contract's `version` by 1 even though the ticket is a separate resource; this is deliberate, so that a billing clerk issuing a settlement can observe whether new ticket data arrived after they last read the contract. State transitions described in §3 likewise increment the acting resource's `version` and refresh its `updated_at`.

### 2.5. The Season Logical Clock

The system maintains a logical clock rather than reading wall-clock time. Before anyone has advanced it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time. A `HarvestOperator` may advance the logical clock to a supplied instant by providing `to_iso8601`; the capability responds with the clock's new reading as `current_utc`. Visa expiry checks at crew activation, the `issued_at` timestamp stamped on settlements, and every other date-based rule in the system all read this logical clock.

### 2.6. Request Validation Order and Nested Path Resolution

When several checks could reject the same request, the system evaluates them in a fixed order so that the returned error is deterministic. The order is:

1. **Header presence** — `X-User-ID` and `X-User-Role` present and well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role permission** — the role may perform this operation, else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).
3. **Existence** — resource identifiers in the URL path must exist, validated left-to-right from the outermost parent inward (season, then contract, then stop, then the child resource). A missing identifier yields the corresponding not-found error — `ERR_SEASON_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_LODGING_SITE_NOT_FOUND`, or `ERR_RESERVATION_NOT_FOUND` — each with HTTP 404.
4. **State legality** — the target resource must be in a state that permits the requested transition, else the transition-specific state error (HTTP 409) described in §3.
5. **Business rules** — domain-specific temporal, safety, constraint, and fiscal checks, each paired with its own error code in §3.

Within the business-rule tier, relative ordering matters on endpoints that carry more than one such rule. When a crew boss departs for a stop, the sequence-ordering check (which can reject with `ERR_OUT_OF_SEQUENCE`) is evaluated before the combine-presence check (`ERR_NO_COMBINE_ASSIGNED`), so a stop that fails both surfaces the sequencing error. When a billing clerk issues a settlement, the contract-must-be-harvested check (`ERR_CONTRACT_NOT_HARVESTED`) is evaluated before the optimistic-concurrency check (`ERR_STALE_VERSION`), so a premature issue attempt reports the contract state rather than a version mismatch.

Requests with a malformed body — a missing required field or a value of the wrong type — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control. A close-season request must carry `expected_season_version`, a non-optional field holding the `version` of the harvest season as the client last observed it. If the season's current `version` does not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where another writer has just moved a settlement to `PAID` or `RESOLVED` — a change that legitimately advances the season's version through contract-side cascade tracking — and the closing client's view of the season is stale. Likewise, an issue-settlement request must carry `expected_contract_version`, a non-optional field holding the `version` of the parent customer contract as the client last observed it; a mismatch with the contract's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where a late delivery ticket was posted against the contract — which bumps the contract's `version` — and the issuer's computed totals would rest on stale ticket data. Endpoints other than these two do not take a version field.

### 2.8. Money, Precision, and Rounding

All monetary amounts are integer cents. Every monetary computation rounds half-up to 0 decimal places (whole cents). The sole exception is `net_bushels` on a delivery ticket, which is a quantity, not money: it is rounded half-up to one decimal place. Field-measured moisture is recorded to one decimal place (for example, 14.5). No computation in the system uses approximate or conservative estimation; every formula in §3 is exact and deterministic.

### 2.9. Date Windows and Half-Open Intervals

Two kinds of date ranges appear in this domain, and both are **half-open**: the start date is inclusive and the end date is exclusive. A machine assignment commits a machine to a stop from `assigned_start_date` (inclusive) up to but not including `assigned_end_date`. A lodging reservation occupies beds from `stay_start_date` (check-in, inclusive) up to but not including `stay_end_date` (check-out, exclusive). Half-open semantics mean adjacency is always allowed: one assignment ending on June 10 and another beginning on June 10 do not overlap. Dates are calendar dates in `YYYY-MM-DD` form; capacity and overlap arithmetic is day-granular (or night-granular for lodging). By contrast, a route stop's planned cutting window, `planned_start_date` to `planned_end_date`, is inclusive at both ends, and `planned_end_date` must not fall before `planned_start_date`.

---

## 3. Business Logic & Workflows

### 3.1. Standing Up a Season: Diesel Baselines and Activation

A `HarvestOperator` opens the year by creating a **harvest season**, supplying the `season_year` (for example, 2026), the `diesel_baseline_per_gallon_cents` against which fuel surcharges will be measured, and the `current_diesel_per_gallon_cents` prevailing at setup time. A new season begins in `DRAFT` status.

While the season is in `DRAFT` or `ACTIVE`, the operator may update either diesel price; each update increments the season's `version` by 1. Once the season has moved on to `SETTLING` or `CLOSED`, the prices are frozen history. The season resource also exposes two read-only computed totals: `committed_acres_total`, the sum of `committed_acres` across contracts whose status is `COMMITTED`, `IN_PROGRESS`, or `HARVESTED`, and `harvested_acres_total`, the sum of `actual_acres` across route stops whose status is `COMPLETED`. Both start at 0 and are recomputed by the system as contracts and stops change.

Activation moves the season from `DRAFT` to `ACTIVE` and is allowed only when three conditions hold: the season is in `DRAFT` (otherwise `ERR_SEASON_NOT_DRAFT`, HTTP 409); the season references at least one machine of kind `COMBINE` currently in `AVAILABLE` status (otherwise `ERR_NO_COMBINE_AVAILABLE`, HTTP 409); and both diesel price fields are greater than zero. Activation increments the season's `version` by 1.

### 3.2. Grower Contracts and the Cutting Route

With a season in place, a `GrowerLiaison` creates **customer contracts** under it, one per grower. Each contract records the `grower_name`, the two-letter `state_code` where the fields lie (the run crosses TX, OK, KS, NE, SD, and ND), the `crop` (one of `WHEAT`, `CORN`, `SOYBEAN`, `SORGHUM`), and the pricing basis. The `rate_basis` field is either `PER_ACRE` or `PER_BUSHEL` and drives which invoice variant is used at settlement. When `rate_basis` is `PER_ACRE`, the `rate_cents_per_acre` field carries the cents charged per harvested acre and `rate_cents_per_bushel` is ignored; when `rate_basis` is `PER_BUSHEL`, the roles reverse — `rate_cents_per_bushel` carries the per-delivered-bushel price and `rate_cents_per_acre` is ignored. The grower's seasonal commitment is recorded in `committed_acres`. A new contract is `DRAFT`.

Committing a contract — a `GrowerLiaison` action — moves it `DRAFT → COMMITTED`. The contract must be in `DRAFT` (otherwise `ERR_CONTRACT_NOT_DRAFT`, HTTP 409), the parent season must be in `DRAFT` or `ACTIVE` (otherwise `ERR_SEASON_NOT_OPEN_FOR_COMMIT`, HTTP 409), and `committed_acres` must be greater than zero. On commit, the season's `committed_acres_total` is recomputed to include this contract, and the contract's `version` increments by 1. The contract's read-only `harvested_acres` field tracks the sum of `actual_acres` over its completed stops, and its read-only `moisture_discount_total_cents` accumulates moisture discounts across issued settlements; both start at 0.

Each contract's fields are cut in one or more **route stops**, created under the contract by the liaison. A stop carries `planned_start_date` and `planned_end_date` (an inclusive planned cutting window, with the end not before the start), the `planned_acres` scheduled there, and a `sequence_index` that orders the stop within the season — `sequence_index` is unique per season across all contracts, because the crew physically works one stop at a time as it moves north. Stops also record `actual_acres`, the acres actually cut, which starts at 0 and is editable by the `CrewBoss` only while the stop is `CUTTING` or `PAUSED_WEATHER`; each edit increments the stop's `version`. A new stop is `SCHEDULED`. The system stamp linking a stop to its contract is carried on `contract_id`, and `season_id` is denormalized onto the stop for filtering.

A contract in `DRAFT` or `COMMITTED` may be cancelled by the liaison (any other state yields `ERR_CONTRACT_NOT_CANCELLABLE`, HTTP 409). Cancellation cascades: every stop of the contract still in `SCHEDULED` transitions to `SKIPPED`; each such stop's `RESERVED` machine assignments transition to `CANCELLED`, releasing each affected machine back to `AVAILABLE` if it is not allocated to any other active assignment; and the season's `committed_acres_total` is recomputed to exclude the cancelled contract. The contract's `version` increments by 1.

### 3.3. Machines, Crew, and Lodging Sites

The operator registers the fleet as **machines** under a season, each with a `machine_kind` of `COMBINE`, `GRAIN_CART`, or `TRUCK`, an operator-facing `label` such as "Combine-03", and a `daily_capacity_acres` figure. `daily_capacity_acres` expresses the maximum acres per day for a combine; it is ignored for grain carts and trucks but must be greater than zero for every machine. Machines are born `AVAILABLE`.

Seasonal labor is onboarded as **crew members** under the season, recording `full_name`, `visa_type` (one of `US_CITIZEN`, `H2A`, `TN`, `PERMANENT_RESIDENT`), `hourly_rate_cents`, and whether the operator must provide lodging (`requires_housing`, which defaults to true when not supplied). For `H2A` and `TN` workers a `visa_expiry_date` in `YYYY-MM-DD` form is required; for citizens and permanent residents it is ignored. A new crew member is `ONBOARDED`.

Activation moves a crew member `ONBOARDED → ACTIVE`. The member must be `ONBOARDED` (otherwise `ERR_CREW_NOT_ONBOARDED`, HTTP 409), the parent season must be in `DRAFT` or `ACTIVE`, and — the safety gate — if the worker's `visa_type` is `H2A` or `TN`, the `visa_expiry_date` must be strictly greater than the season's current logical date as read from the logical clock; an expiry date equal to or earlier than the logical date is rejected with `ERR_VISA_EXPIRED` (HTTP 422). Releasing a crew member requires the member to be `ACTIVE` (otherwise `ERR_CREW_NOT_ACTIVE`, HTTP 409) and is blocked while the member holds any lodging reservation in `BOOKED` or `CHECKED_IN` status overlapping any future date (`ERR_ACTIVE_LODGING_EXISTS`, HTTP 409). On release, all future `BOOKED` reservations for that member transition to `CANCELLED`, and the member becomes `RELEASED`.

Finally, the operator registers **lodging sites** under the season — motels, bunkhouses, RV parks — each with a `site_name`, the `state_code` where it sits, and a `total_beds` capacity that must be greater than zero.

### 3.4. Running a Stop: Machines, Departure, Cutting, and Completion

Before any wheels turn, the `CrewBoss` reserves machines against a stop by creating **machine assignments** naming the `route_stop_id`, the `machine_id`, and a half-open window from `assigned_start_date` (inclusive) to `assigned_end_date` (exclusive). A new assignment is `RESERVED`. Two rules guard creation. First, the overlap rule: the request is rejected with `ERR_MACHINE_OVERLAP` (HTTP 409) if any existing assignment for the same machine in `RESERVED` or `DEPLOYED` status has a start date earlier than the new assignment's end date while the new assignment's start date is earlier than that existing assignment's end date. Under half-open semantics, pure adjacency — the new start equal to an existing end, or the new end equal to an existing start — is allowed. Second, the machine's own status reacts: when the first active reservation is created against an `AVAILABLE` machine, the machine transitions to `ASSIGNED`.

Departure is the point of commitment. A `CrewBoss` departs for a stop, transitioning it `SCHEDULED → EN_ROUTE`, only when all of the following hold, evaluated after the generic checks of §2.6: the stop is `SCHEDULED` (otherwise `ERR_STOP_NOT_SCHEDULED`, HTTP 409); the parent season is `ACTIVE` (otherwise `ERR_SEASON_NOT_ACTIVE`, HTTP 409); the stop has at least one machine assignment in `RESERVED` or `DEPLOYED` whose machine is of kind `COMBINE` (otherwise `ERR_NO_COMBINE_ASSIGNED`, HTTP 409); and no other stop in the same season with a strictly smaller `sequence_index` is still in `SCHEDULED`, `EN_ROUTE`, `CUTTING`, or `PAUSED_WEATHER` (otherwise `ERR_OUT_OF_SEQUENCE`, HTTP 409) — the route runs in order, and an earlier-indexed stop still in any active state blocks later departures. Recall from §2.6 that when both the sequencing rule and the combine rule would fail, the sequencing error is reported. On departure, every `RESERVED` assignment on the stop transitions to `DEPLOYED`, and their machines transition `ASSIGNED → IN_FIELD`; the stop's `version` increments by 1.

Arrival in the field becomes cutting: the crew boss starts cutting, moving the stop `EN_ROUTE → CUTTING`. The stop must be `EN_ROUTE` (otherwise `ERR_STOP_NOT_EN_ROUTE`, HTTP 409), and at least one `DEPLOYED` assignment on the stop must reference a machine that is `IN_FIELD` and of kind `COMBINE`. Starting cutting cascades upward: the parent contract transitions `COMMITTED → IN_PROGRESS` automatically. The stop's `version` increments by 1.

Weather is a fact of the plains. From `CUTTING`, the crew boss may pause for weather (`CUTTING → PAUSED_WEATHER`; a stop not in `CUTTING` yields `ERR_STOP_NOT_CUTTING`, HTTP 409), and from `PAUSED_WEATHER` may resume (`PAUSED_WEATHER → CUTTING`; a stop not paused yields `ERR_STOP_NOT_PAUSED`, HTTP 409). Each transition increments the stop's `version`. While paused or cutting, the crew boss continues to update `actual_acres` as the acres accumulate.

Completion moves a stop `CUTTING → COMPLETED`. The stop must be `CUTTING` (otherwise `ERR_STOP_NOT_CUTTING`), `actual_acres` must be greater than zero, and `actual_acres` must not exceed one hundred ten percent of `planned_acres` — an overrun beyond that ceiling is rejected with `ERR_ACRES_OVERRUN` (HTTP 422). Completion is the widest cascade in the system: every `DEPLOYED` assignment on the stop transitions to `RELEASED`; each released machine transitions `IN_FIELD → AVAILABLE` if it is not allocated to any other `DEPLOYED` assignment, and stays `IN_FIELD` otherwise; every lodging reservation on the stop in `BOOKED` or `CHECKED_IN` transitions to `CHECKED_OUT`; the parent contract's `harvested_acres` is recomputed as the sum of `actual_acres` over its `COMPLETED` stops; if every stop of the parent contract has reached `COMPLETED` or `SKIPPED`, the contract auto-transitions `IN_PROGRESS → HARVESTED`; and the season's `harvested_acres_total` is recomputed. The stop's `version` increments by 1.

A stop that will not be cut at all can be skipped by the `HarvestOperator`, but only from `SCHEDULED` (otherwise `ERR_STOP_NOT_SKIPPABLE`, HTTP 409), moving it to `SKIPPED`. Skipping cancels the stop's `RESERVED` assignments (releasing each machine to `AVAILABLE` if not allocated elsewhere) and cancels its `BOOKED` lodging reservations; the stop's `version` increments by 1.

### 3.5. Breakdown and Recovery

Machines fail in the field, and the system models the whole repair loop. A `CrewBoss` reports a breakdown on a machine that is `IN_FIELD` (otherwise `ERR_MACHINE_NOT_IN_FIELD`, HTTP 409), moving it `IN_FIELD → DOWN`. The breakdown has an immediate operational cascade: every route stop that currently holds a `DEPLOYED` assignment for this machine and is itself in `CUTTING` or `PAUSED_WEATHER` transitions to `PAUSED_WEATHER`.

From there the operator drives recovery: dispatching a repair moves the machine `DOWN → REPAIRING` (it must be `DOWN`, otherwise `ERR_MACHINE_NOT_DOWN`, HTTP 409), and returning it to service moves it `REPAIRING → AVAILABLE` (it must be `REPAIRING`, otherwise `ERR_MACHINE_NOT_REPAIRING`, HTTP 409). When a machine returns to service, any stop that was pushed into `PAUSED_WEATHER` by the breakdown cascade and still has at least one other deployed combine available becomes eligible to resume — but resumption is never automatic; the crew boss must explicitly resume the stop.

Machine status otherwise moves with assignments: the first `RESERVED` assignment against an `AVAILABLE` machine moves it to `ASSIGNED`; deployment of one of its `RESERVED` assignments at departure moves it `ASSIGNED → IN_FIELD`; release of its last `DEPLOYED` assignment moves it back to `AVAILABLE`; and cancellation of its last `RESERVED` assignment while it is `ASSIGNED` returns it to `AVAILABLE`. Cancelling an individual assignment — a `CrewBoss` action allowed only while the assignment is `RESERVED` (otherwise `ERR_ASSIGNMENT_NOT_RESERVED`, HTTP 409) — moves it to `CANCELLED`, and if that was the machine's last non-cancelled assignment and the machine was `ASSIGNED`, the machine returns to `AVAILABLE`. At season close, every machine in the season transitions to `RETIRED`, the machine's terminal state.

### 3.6. Crew Housing and Bed Management

As the crew moves, the `CrewBoss` books **lodging reservations** under a route stop, naming the `crew_member_id`, the `lodging_site_id`, a half-open stay from `stay_start_date` (check-in, inclusive) to `stay_end_date` (check-out, exclusive), and optionally a `bed_count` that defaults to 1. A new reservation is `BOOKED`.

Beds are fungible, so capacity is checked per night rather than per reservation: for each calendar date within the requested stay range, the system sums the `bed_count` of every reservation at the same lodging site in `BOOKED` or `CHECKED_IN` status whose own stay range covers that date; if the occupied total plus the new reservation's `bed_count` would exceed the site's `total_beds` on any night of the stay, the booking is rejected with `ERR_LODGING_CAPACITY_EXCEEDED` (HTTP 409). This aggregate-capacity semantics deliberately differs from the machine overlap rule: overlapping stays are fine as long as no single night overflows the site.

A booked reservation is checked in by the crew boss (`BOOKED → CHECKED_IN`; a reservation not in `BOOKED` yields `ERR_RESERVATION_NOT_BOOKED`, HTTP 409), and checked out either explicitly (`CHECKED_IN → CHECKED_OUT`) or automatically when the stop completes — completion sweeps both `BOOKED` and `CHECKED_IN` reservations on the stop into `CHECKED_OUT`. A `BOOKED` reservation may instead be cancelled by the crew boss (any other status yields `ERR_RESERVATION_NOT_CANCELLABLE`, HTTP 409), moving it to `CANCELLED`; skipping a stop cancels its `BOOKED` reservations as a cascade, and releasing a crew member cancels that member's future `BOOKED` reservations.

### 3.7. Grain Delivery and Moisture Adjustment

While a stop is being cut, trucks dump at the elevator and the `CrewBoss` records each load as a **delivery ticket** under the route stop, supplying `delivered_at` (the timestamp of the dump), `gross_bushels` from the scale ticket, the measured `moisture_pct` to one decimal place, and `used_our_trucks`, which records whether the harvester's own trucks hauled the load rather than the grower's. Tickets are append-only; no status filter ever excludes them from settlement math. The ticket's `contract_id` is denormalized from its stop for filtering and settlement aggregation.

Two values are computed at ticket write time and frozen. First, `net_bushels`: the system derives a moisture shrink factor from `moisture_pct`. If the moisture percent is at most 15.0, the shrink factor is exactly 1.0 — no shrink. Otherwise, the system counts excess tenths by taking the difference between the moisture percent and 15.0, multiplying by ten, and rounding half-up to a whole number; the shrink factor is then one minus the product of the excess tenths and 0.001, but never lower than 0.80 — the maximum shrink is capped at 0.20. `net_bushels` is the gross bushels multiplied by the shrink factor, rounded half-up to one decimal place. Second, `hauling_add_on_cents`: if `used_our_trucks` is true, the add-on is the gross bushels multiplied by twelve cents per bushel, rounded half-up to whole cents; if the grower hauled the load, the add-on is 0.

Posting a ticket also increments the parent contract's `version` by 1. This is the intended serialization point with settlement issuance: a ticket posted after a billing clerk last read the contract makes the clerk's `expected_contract_version` stale, so the late load cannot slip silently into — or out of — an issued settlement.

### 3.8. Settlement, Disputes, and Season Close

When the cutting is done, the `HarvestOperator` opens the settlement window, moving the season `ACTIVE → SETTLING`. The season must be `ACTIVE` (otherwise `ERR_SEASON_NOT_ACTIVE`), and no route stop in the season may still be in `EN_ROUTE`, `CUTTING`, or `PAUSED_WEATHER` (otherwise `ERR_STOPS_STILL_RUNNING`, HTTP 409). Opening settlement force-resolves the stragglers: every stop still in `SCHEDULED` transitions to `SKIPPED`, each such stop's `RESERVED` assignments transition to `CANCELLED`, and each machine those assignments held returns to `AVAILABLE` if it was `ASSIGNED` and is not allocated to any other `RESERVED` or `DEPLOYED` assignment. The season's `version` increments by 1.

A `BillingClerk` then creates a **settlement** under a contract; it begins in `DRAFT`. Issuing the settlement — the computational heart of the system — requires three preconditions, evaluated in the order given in §2.6: the settlement must be in `DRAFT` (otherwise `ERR_SETTLEMENT_NOT_DRAFT`, HTTP 409); the parent contract must be in `HARVESTED`, meaning every one of its stops has reached `COMPLETED` or `SKIPPED` (otherwise `ERR_CONTRACT_NOT_HARVESTED`, HTTP 409); and the parent season must be in `SETTLING` (otherwise `ERR_SEASON_NOT_SETTLING`, HTTP 409). The request must also carry `expected_contract_version` matching the contract's current `version`, per the OCC rule in §2.7 — a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and this check runs after the harvested check.

Issuance computes and permanently freezes five amounts, in a pinned evaluation order — base first, then fuel surcharge, then hauling, then moisture discount — and stamps `issued_at` with the current logical clock.

1. **`base_amount_cents`.** Let A be the contract's `harvested_acres` at issue time, and let NB be the sum of `net_bushels` over every delivery ticket for the contract. If the contract's `rate_basis` is `PER_ACRE`, the base is A multiplied by the contract's `rate_cents_per_acre`, rounded half-up to whole cents; bushels are ignored. If `rate_basis` is `PER_BUSHEL`, tiered pricing applies to NB: when NB is at most 10,000 bushels, the base is NB multiplied by `rate_cents_per_bushel`, rounded half-up to whole cents; when NB exceeds 10,000, the first 10,000 bushels are priced at `rate_cents_per_bushel` and the remainder at `rate_cents_per_bushel` multiplied by 0.9 — a ten percent volume discount — with the sum of the two tiers rounded half-up to whole cents. Harvested acres play no part in the per-bushel variant.
2. **`fuel_surcharge_cents`.** Let the delta be the season's `current_diesel_per_gallon_cents` as it stands at issue time minus `diesel_baseline_per_gallon_cents`, divided by `diesel_baseline_per_gallon_cents`. If the delta is strictly less than 0.10, the surcharge is zero. If the delta is greater than or equal to 0.10 — note the boundary is inclusive, so a delta of exactly 0.10 triggers the surcharge — the surcharge is `base_amount_cents` multiplied by the delta and then multiplied by 0.5 (half of the increase is passed through to the grower), rounded half-up to whole cents.
3. **`hauling_add_on_total_cents`.** The sum of `hauling_add_on_cents` across all delivery tickets for this contract.
4. **`moisture_discount_cents`.** This discount applies only when `rate_basis` is `PER_ACRE`; under `PER_BUSHEL` the shrink is already reflected in net bushels, so a second discount would double-count and the value is zero. For a per-acre contract, the system examines every ticket whose `moisture_pct` exceeds 15.0, counts each such ticket's excess tenths exactly as in the shrink calculation (the difference from 15.0, multiplied by ten, rounded half-up to a whole number), and charges 200 cents per excess tenth per affected ticket; `moisture_discount_cents` is the sum of those per-ticket penalties in whole cents.
5. **`total_amount_cents`.** The base plus the fuel surcharge plus the hauling total minus the moisture discount, floored at zero — the total never goes negative. Hauling is added before the moisture discount is subtracted so the discount cannot erode the hauling recovery.

Issuance moves the settlement `DRAFT → ISSUED`, increments the settlement's `version`, increments the contract's `moisture_discount_total_cents` by this settlement's `moisture_discount_cents`, and increments the contract's `version` by 1.

An issued settlement has two exits. The clerk marks it paid (`ISSUED → PAID`; a settlement not in `ISSUED` yields `ERR_SETTLEMENT_NOT_ISSUED`, HTTP 409), which auto-transitions the parent contract `HARVESTED → SETTLED`. Alternatively, the `GrowerLiaison` disputes it on the grower's behalf (`ISSUED → DISPUTED`; likewise requiring `ISSUED`, else `ERR_SETTLEMENT_NOT_ISSUED`). A disputed settlement is resolved by the clerk (`DISPUTED → RESOLVED`; any other state yields `ERR_SETTLEMENT_NOT_DISPUTED`, HTTP 409), and the resolution request must carry a `resolution_note`, a non-empty string. Resolution, like payment, auto-transitions the parent contract `HARVESTED → SETTLED`.

With every settlement settled, the operator closes the season (`SETTLING → CLOSED`). The season must be `SETTLING` (otherwise `ERR_SEASON_NOT_SETTLING`), and every settlement whose contract belongs to the season must be in `PAID` or `RESOLVED` (otherwise `ERR_UNRESOLVED_SETTLEMENTS_EXIST`, HTTP 409). The request must carry `expected_season_version` per §2.7; a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412). Closing retires every machine in the season to `RETIRED`, releases every crew member still in `ACTIVE` to `RELEASED`, and increments the season's `version` by 1.

---

## 4. Endpoint Definitions

All endpoints are mounted under `/harvest`. Creating a new resource returns HTTP 201 with the created resource; state transitions, modifications, and the clock capability return HTTP 200 with the affected resource (or the clock payload). List and detail retrievals return HTTP 200. Every write described in §3 increments the acting resource's `version` as stated there; retrievals have no side effects. Readers should reconstruct full request payloads from the §3 narratives — this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/harvest/_clock/set_current_utc` | Advance the logical clock; before any call it reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock | HarvestOperator |
| POST | `/harvest/seasons` | Create a new harvest season | HarvestOperator |
| GET | `/harvest/seasons` | List harvest seasons | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/seasons/{seasonId}` | Get one harvest season | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| PATCH | `/harvest/seasons/{seasonId}` | Update diesel prices (only while DRAFT or ACTIVE) | HarvestOperator |
| POST | `/harvest/seasons/{seasonId}/activate` | Activate the season (DRAFT → ACTIVE) | HarvestOperator |
| POST | `/harvest/seasons/{seasonId}/open-settlement` | Open settlement window (ACTIVE → SETTLING); skips still-SCHEDULED stops | HarvestOperator |
| POST | `/harvest/seasons/{seasonId}/close` | Close the season (SETTLING → CLOSED); OCC-guarded via `expected_season_version` | HarvestOperator |
| POST | `/harvest/seasons/{seasonId}/contracts` | Create a customer contract under a season | GrowerLiaison |
| GET | `/harvest/contracts` | List contracts; filterable by `season_id` and `status` | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/seasons/{seasonId}/contracts` | List contracts under a season | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/contracts/{contractId}` | Get one contract | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| POST | `/harvest/contracts/{contractId}/commit` | Commit the contract (DRAFT → COMMITTED) | GrowerLiaison |
| POST | `/harvest/contracts/{contractId}/cancel` | Cancel a contract in DRAFT or COMMITTED | GrowerLiaison |
| POST | `/harvest/contracts/{contractId}/route-stops` | Create a route stop under a contract | GrowerLiaison |
| GET | `/harvest/contracts/{contractId}/route-stops` | List stops for a contract | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/route-stops` | List route stops; filterable by `contract_id` or `season_id` | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/route-stops/{stopId}` | Get one route stop | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| PATCH | `/harvest/route-stops/{stopId}` | Update `actual_acres` (only while CUTTING or PAUSED_WEATHER) | CrewBoss |
| POST | `/harvest/route-stops/{stopId}/depart` | Depart for stop (SCHEDULED → EN_ROUTE) | CrewBoss |
| POST | `/harvest/route-stops/{stopId}/start-cutting` | Begin cutting (EN_ROUTE → CUTTING) | CrewBoss |
| POST | `/harvest/route-stops/{stopId}/pause-weather` | Pause for weather (CUTTING → PAUSED_WEATHER) | CrewBoss |
| POST | `/harvest/route-stops/{stopId}/resume` | Resume from weather pause (PAUSED_WEATHER → CUTTING) | CrewBoss |
| POST | `/harvest/route-stops/{stopId}/complete` | Mark stop complete (CUTTING → COMPLETED) | CrewBoss |
| POST | `/harvest/route-stops/{stopId}/skip` | Skip a SCHEDULED stop (→ SKIPPED) | HarvestOperator |
| POST | `/harvest/seasons/{seasonId}/machines` | Register a machine | HarvestOperator |
| GET | `/harvest/seasons/{seasonId}/machines` | List machines for a season | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/machines` | List machines; filterable by `season_id` | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/machines/{machineId}` | Get one machine | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| POST | `/harvest/machines/{machineId}/report-breakdown` | Mark machine DOWN; pauses stops currently using it | CrewBoss |
| POST | `/harvest/machines/{machineId}/dispatch-repair` | Move machine DOWN → REPAIRING | HarvestOperator |
| POST | `/harvest/machines/{machineId}/return-to-service` | Move machine REPAIRING → AVAILABLE | HarvestOperator |
| POST | `/harvest/seasons/{seasonId}/crew-members` | Onboard a crew member | HarvestOperator |
| GET | `/harvest/seasons/{seasonId}/crew-members` | List crew for a season | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/crew-members` | List crew members; filterable by `season_id` | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/crew-members/{crewId}` | Get one crew member | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| POST | `/harvest/crew-members/{crewId}/activate` | Activate crew member (visa check) | HarvestOperator |
| POST | `/harvest/crew-members/{crewId}/release` | Release a crew member | HarvestOperator |
| POST | `/harvest/machine-assignments` | Reserve a machine against a route stop | CrewBoss |
| GET | `/harvest/machine-assignments` | List assignments; filterable by `route_stop_id` or `machine_id` | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/machine-assignments/{assignmentId}` | Get one assignment | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| POST | `/harvest/machine-assignments/{assignmentId}/cancel` | Cancel a RESERVED assignment | CrewBoss |
| POST | `/harvest/route-stops/{stopId}/delivery-tickets` | Record a grain delivery | CrewBoss |
| GET | `/harvest/route-stops/{stopId}/delivery-tickets` | List tickets for a stop | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/delivery-tickets` | List delivery tickets; filterable by `route_stop_id` or `contract_id` | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/delivery-tickets/{ticketId}` | Get one ticket | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| POST | `/harvest/contracts/{contractId}/settlements` | Create a DRAFT settlement for a contract | BillingClerk |
| GET | `/harvest/contracts/{contractId}/settlements` | List settlements for a contract | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/settlements` | List settlements; filterable by `contract_id` or `season_id` | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/settlements/{settlementId}` | Get one settlement | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| POST | `/harvest/settlements/{settlementId}/issue` | Issue the settlement (computes and freezes all amounts); OCC via `expected_contract_version` | BillingClerk |
| POST | `/harvest/settlements/{settlementId}/mark-paid` | Mark an ISSUED settlement PAID | BillingClerk |
| POST | `/harvest/settlements/{settlementId}/dispute` | Dispute an ISSUED settlement on the grower's behalf | GrowerLiaison |
| POST | `/harvest/settlements/{settlementId}/resolve` | Resolve a disputed settlement (requires `resolution_note`) | BillingClerk |
| POST | `/harvest/seasons/{seasonId}/lodging-sites` | Register a lodging site | HarvestOperator |
| GET | `/harvest/seasons/{seasonId}/lodging-sites` | List lodging sites for a season | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/lodging-sites` | List lodging sites; filterable by `season_id` | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/lodging-sites/{siteId}` | Get one lodging site | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| POST | `/harvest/route-stops/{stopId}/lodging-reservations` | Book beds for a crew member during a stop | CrewBoss |
| GET | `/harvest/route-stops/{stopId}/lodging-reservations` | List lodging reservations for a stop | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/lodging-reservations` | List lodging reservations; filterable by `route_stop_id` or `crew_member_id` | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| GET | `/harvest/lodging-reservations/{resId}` | Get one lodging reservation | HarvestOperator, CrewBoss, GrowerLiaison, BillingClerk |
| POST | `/harvest/lodging-reservations/{resId}/check-in` | Check in a BOOKED reservation | CrewBoss |
| POST | `/harvest/lodging-reservations/{resId}/check-out` | Check out a CHECKED_IN reservation | CrewBoss |
| POST | `/harvest/lodging-reservations/{resId}/cancel` | Cancel a BOOKED reservation | CrewBoss |

---

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives where the guarded workflow lives; this table is the canonical identifier-to-status mapping.

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SEASON_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_STOP_NOT_FOUND` | 404 |
| `ERR_MACHINE_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_LODGING_SITE_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_SEASON_NOT_DRAFT` | 409 |
| `ERR_SEASON_NOT_ACTIVE` | 409 |
| `ERR_SEASON_NOT_SETTLING` | 409 |
| `ERR_NO_COMBINE_AVAILABLE` | 409 |
| `ERR_STOPS_STILL_RUNNING` | 409 |
| `ERR_UNRESOLVED_SETTLEMENTS_EXIST` | 409 |
| `ERR_CONTRACT_NOT_DRAFT` | 409 |
| `ERR_CONTRACT_NOT_CANCELLABLE` | 409 |
| `ERR_CONTRACT_NOT_HARVESTED` | 409 |
| `ERR_SEASON_NOT_OPEN_FOR_COMMIT` | 409 |
| `ERR_STOP_NOT_SCHEDULED` | 409 |
| `ERR_STOP_NOT_EN_ROUTE` | 409 |
| `ERR_STOP_NOT_CUTTING` | 409 |
| `ERR_STOP_NOT_PAUSED` | 409 |
| `ERR_STOP_NOT_SKIPPABLE` | 409 |
| `ERR_MACHINE_NOT_IN_FIELD` | 409 |
| `ERR_MACHINE_NOT_DOWN` | 409 |
| `ERR_MACHINE_NOT_REPAIRING` | 409 |
| `ERR_CREW_NOT_ONBOARDED` | 409 |
| `ERR_CREW_NOT_ACTIVE` | 409 |
| `ERR_ACTIVE_LODGING_EXISTS` | 409 |
| `ERR_ASSIGNMENT_NOT_RESERVED` | 409 |
| `ERR_SETTLEMENT_NOT_DRAFT` | 409 |
| `ERR_SETTLEMENT_NOT_ISSUED` | 409 |
| `ERR_SETTLEMENT_NOT_DISPUTED` | 409 |
| `ERR_RESERVATION_NOT_BOOKED` | 409 |
| `ERR_RESERVATION_NOT_CANCELLABLE` | 409 |
| `ERR_OUT_OF_SEQUENCE` | 409 |
| `ERR_MACHINE_OVERLAP` | 409 |
| `ERR_LODGING_CAPACITY_EXCEEDED` | 409 |
| `ERR_ACRES_OVERRUN` | 422 |
| `ERR_NO_COMBINE_ASSIGNED` | 409 |
| `ERR_VISA_EXPIRED` | 422 |
| `ERR_STALE_VERSION` | 412 |
