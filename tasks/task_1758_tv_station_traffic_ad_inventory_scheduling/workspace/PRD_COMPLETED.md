# TV Station Traffic & Ad Inventory Scheduling API — Product Requirements Document

## 1. Introduction

A local network affiliate sells its broadcast day one commercial break at a time. Between the sales desk that signs advertisers and the master-control room that airs the log sits the traffic department: the team that decides which spots occupy which breaks, keeps competing car dealers out of the same pod, reserves inventory when a declared political window activates lowest-unit-charge obligations, and — when a spot fails to air or a guaranteed audience fails to materialize — computes what the station owes back. This document specifies the API that runs that operation end to end: avail inventory by daypart and program, order entry with rate and rating guarantees, log generation with commercial separation and copy rotation, preemption and make-good scheduling, and as-run reconciliation feeding discrepancy credits and post-buy audience-delivery analysis.

The API is mounted under `/traffic` and models the full chain from sales order to reconciled log. Five station roles share the workload — sales, traffic, copy/continuity, billing, and system administration — and all calendar-sensitive behavior is driven by a server-side logical clock so that flight windows, log finalization, and order completion are deterministic. Implementers should read Section 2 for system-wide contracts, Section 3 for the business workflows those contracts serve, and Sections 4 and 5 for the endpoint and error references.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API: authentication, response envelopes, pagination, resource identity, the logical clock, inventory counters, numeric precision, concurrency control, and the ordered validation pipeline.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled as follows: `SalesRep` (the station account executive who builds orders, owns the advertiser relationship, requests revisions, and declines make-goods), `TrafficManager` (the traffic manager who owns programs, avail inventory, log building, order approval, placement, preemption, and make-goods), `CopyCoordinator` (the copy/continuity desk that registers advertiser copy and clears or withdraws it), `BillingClerk` (the billing and reconciliation clerk who posts as-run reconciliation and reads post-buy credit reports), and `StationAdmin` (the station system administrator who operates the logical clock and reads everything). A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose authenticated role is not in the target endpoint's authorized list is rejected with `ERR_FORBIDDEN`.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. This applies individually to `SalesRep`, `TrafficManager`, `CopyCoordinator`, `BillingClerk`, and `StationAdmin` alike: the server never compares `X-User-ID` against any resource's `id`, and no ownership check is derived from it. Authorization is determined purely by `X-User-Role`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100 — out-of-range values are clamped into that interval rather than rejected, and a value that does not parse as an integer falls back to the default. The `offset` parameter states how many items to skip and defaults to 0; a negative offset is clamped to 0 and a value that does not parse as an integer falls back to the default. Unless stated otherwise, every list endpoint returns resources sorted by creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Beyond the filters enumerated in Section 3, every list endpoint over a resource that carries a `status` field also accepts an optional `status` query filter that keeps only resources currently in that status, whether or not Section 3 calls it out; the flat order list additionally accepts an `advertiser_id` filter. A non-integer value supplied to an integer filter is rejected with `ERR_INVALID_REQUEST`.

### 2.4. Resource Identity and Common Fields

Every primary resource carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits, and `updated_at` records the last modification in the same format. The `version` field is an integer that starts at 1 on creation and increments with every mutation of the resource — including mutations performed as side effects, such as booked-second counter maintenance on an avail unit or budget recomputation on an order. These four fields appear on advertisers, programs, avail weeks, avail units, orders, order lines, copy instructions, spots, and log days.

As-run entries are the deliberate exception. An as-run entry is an append-only reconciliation record: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent. Once posted, an as-run entry is never modified.

### 2.5. The Logical Clock and the Broadcast Calendar

All date-sensitive behavior in the system — flight windows, log finalization eligibility, and order completion — reads a server-side logical clock, never the real wall clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and before any clock-setting call it continues to read exactly that instant. Every server-generated timestamp — the response envelope's `api_request_timestamp` and every resource's `created_at` and `updated_at` — is likewise read from this logical clock. A `StationAdmin` may advance the clock through an admin-only capability that accepts a payload carrying `to_iso8601` and returns the new reading as `current_utc`. The accepted value is any parseable ISO 8601 timestamp: a timezone offset is converted to UTC, a timezone-naive value is read as UTC, and no monotonicity is enforced, so a reading earlier than the current one is accepted. The returned `current_utc` renders in UTC with three fractional digits when the reading carries sub-second precision, and with whole-second precision and no fractional part otherwise. Every clock-setting call, whether or not it advances the reading, also runs the order completion sweep described in §3.4.

The broadcast calendar is anchored on Monday. A broadcast week is opened by supplying its `week_start_date`, conventionally the ISO date of the Monday that opens the week — the server does not verify the weekday and accepts any ISO date — and every date inside the week must fall within the seven days that date opens: the supplied date plus the six days that follow it. Date-window coherence is enforced across the calendar: an order's flight end must not precede its flight start; an avail unit's air date must fall inside its owning week and must land on the weekday its program airs; a log day's date must fall inside its owning week; a spot may only be placed on an air date inside its order's flight; and a log day can only be finalized while its date is today or in the future relative to the logical clock. Each of these violations surfaces as `ERR_DATE_WINDOW` at the point the rule is checked.

### 2.6. Break Inventory Counters and the Political Reserve

Sellable time is tracked per avail unit — one commercial break inside one program on one air date. Each unit declares `total_seconds`, the total sellable commercial seconds in the break, and may declare `reserved_political_seconds`, the portion of those seconds reserved for political spots while a political window is in effect. Two live counters, `booked_commercial_seconds` and `booked_political_seconds`, record the seconds currently held against the break by each class of spot. Both counters start at zero when the unit is created and are maintained thereafter by placement, preemption, cancellation, and reconciliation side effects: placing a spot adds its duration to the bucket matching its class, and preempting or cancelling a scheduled spot releases its duration back.

The political reserve is a one-way fence. It constrains commercial bookings only: a commercial spot may never push commercial bookings past the break's total seconds minus the reserved political seconds. Political spots face no such fence and may occupy any otherwise-free second in the break, whether inside or outside the reserve. Seconds booked by political spots beyond the reserve therefore leave commercial capacity intact per station policy — the full placement arithmetic is defined in §3.5.

### 2.7. Money, Ratings, and Precision

Monetary values are integer cents throughout the API; no fractional cents are stored or returned. Credit computations multiply first and then truncate once — a floor to whole cents applied after the multiplication, with no per-step rounding. Where a credit is aggregated across order lines, the floor is applied per line, never on the order-level total.

Audience delivery is measured in rating points carried at higher precision. The deficit computed for a single aired spot is kept to three decimal places, rounded half up; the per-line rollup sums spot deficits exactly and applies a ceiling to whole audience-deficiency units only at the end. Copy-rotation scores are compared exactly as rational numbers, by cross-multiplication of the score components, and are never rounded to floats. Break inventory arithmetic — headroom and separation — operates on integer seconds and integer positions with no rounding, and capacity boundaries are inclusive: a spot whose duration exactly equals the remaining capacity is accepted, while one second beyond it is rejected.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each names its guard field explicitly.

Approving an order requires the request to carry `expected_order_version`, holding the order `version` the client last observed. If the order's current `version` has advanced since that observation — because another writer added or cancelled a line, or the order was otherwise mutated in the interim — the approval is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), so the client never approves a budget and line set it has not actually seen.

Placing a spot requires the request to carry `expected_avail_unit_version`, holding the target avail unit's `version` the client last observed. Because every placement, preemption, or cancellation against a unit advances that unit's `version`, a mismatch means the client's headroom computation is stale; the placement is rejected with `ERR_STALE_AVAIL_VERSION` (HTTP 412) and must be recomputed against a fresh read before retrying.

Both fields are non-optional inputs on their respective operations. Endpoints other than these two take no version field.

### 2.9. Nested Paths and Hierarchical Consistency

Requests that target nested resources are validated strictly left to right. Each identifier in the URL path is resolved in sequence, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource — a request addressed to an avail unit under a non-existent broadcast week fails on the week before the unit is ever examined. After the path, any `*_id` fields in the request body are resolved the same way, and the first unresolved reference yields `ERR_NOT_FOUND`.

State changes propagate across the hierarchy to keep parent and child consistent. Finalizing any single log day locks its owning broadcast week against further placements; reconciling every log day of a week closes the week. Within an order, adding or cancelling a line recomputes the order's budget and advances the order's `version`, and every order action — submission, approval, rejection, revision, cancellation, completion — advances the order's `version` as well. Every such mutation, primary or cascaded, refreshes the mutated resource's `updated_at`.

### 2.10. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and when several checks would fail, the earliest one in this order determines the error returned.

First, authentication: the headers of §2.1 must be present and valid, else `ERR_UNAUTHENTICATED`. Second, authorization: the acting role must appear in the endpoint's authorized list, else `ERR_FORBIDDEN`. Third, existence: path identifiers and then body references resolve left to right, else `ERR_NOT_FOUND`. Fourth, state legality: the target entity must be in a state from which the requested transition exists — this covers terminal-state lockdowns as well as preemption or finalization attempts against already-finalized logs — else `ERR_INVALID_STATE`. Fifth, date-window coherence per §2.5, else `ERR_DATE_WINDOW`. Sixth, cross-reference coherence — line program resolution, placement program matching, copy length matching, and the make-good comparable-rating rule — else `ERR_REFERENCE_MISMATCH`. Seventh, political inventory protection: a commercial placement that would consume reserved political seconds, or a political-priority preemption attempted against a political spot, is rejected with `ERR_POLITICAL_RESERVE`. Eighth, avail capacity and make-good uniqueness: exhausted headroom or a duplicate outstanding make-good for the same preempted spot yields `ERR_AVAIL_OVERFLOW`. Ninth, commercial separation inside the break, else `ERR_SEPARATION_VIOLATION`. Tenth, log completeness at finalization: any scheduled spot without resolvable copy yields `ERR_COPY_NOT_RECEIVED`. Eleventh, reconciliation payload completeness: missing entries, extra entries, or an aired entry without a measured rating yields `ERR_RECONCILE_MISMATCH`. Twelfth, advertiser credit at approval, else `ERR_CREDIT_LIMIT`. Thirteenth, field-level request sanity — required fields present, enum values valid, prices positive, weights and ratings non-negative where required, spot lengths in the allowed set — else `ERR_INVALID_REQUEST`; this check is evaluated late, after the business rules, so a request that violates both a business rule and a field constraint reports the business error. Finally, fourteenth and fifteenth, the two optimistic-concurrency checks of §2.8: `ERR_STALE_ORDER_VERSION` for order approval and `ERR_STALE_AVAIL_VERSION` for spot placement. Because the stale-version checks run last, a stale version surfaces only on an otherwise-valid request.

## 3. Business Logic & Workflows

### 3.1. Advertisers, Agencies, and Creditworthiness

Everything a station sells traces back to an advertiser. A `SalesRep` registers one by supplying its legal `name`, its `product_category`, and a `credit_limit_cents` ceiling on approved outstanding billing, which must not be negative. When the buy comes through a media agency, the `agency_name` records the agency of record; for direct business the field may be omitted and defaults to an empty string. The `product_category` must be one of `AUTOMOTIVE`, `RETAIL`, `RESTAURANT`, `PHARMA`, `FINANCE`, `POLITICAL`, or `OTHER`, and it does real work: it drives the commercial-separation rules of §3.5, and it decides whether every spot spawned for the advertiser is classed as political or commercial inventory. The advertiser roster can be listed with an optional `product_category` filter.

Creditworthiness is enforced at approval time rather than at order entry. An advertiser's outstanding exposure is the sum of `gross_budget_cents` across its orders currently in `APPROVED` or `COMPLETED` status; §3.4 describes how approval adds the candidate order's budget to that exposure and rejects the approval with `ERR_CREDIT_LIMIT` when the total would exceed `credit_limit_cents`.

### 3.2. Building the Sellable Week: Programs, Avail Weeks, and Break Inventory

Inventory begins with the program grid. A `TrafficManager` registers each program with a `title`, a `daypart_code`, the weekday it airs, its `start_time_local`, its `duration_minutes`, a `rating_estimate`, and an optional `is_political_window` flag. The daypart is one of `EARLY_MORNING`, `DAYTIME`, `EARLY_NEWS`, `PRIME`, `LATE_NEWS`, `LATE_FRINGE`, or `OVERNIGHT`. Programs are modeled per weekday: `airs_weekday` is the ISO weekday the program airs, from 1 for Monday through 7 for Sunday, and a program that airs five days a week is registered as five program rows. The start time is a local 24-hour HH:MM string, the duration must be at least 5 minutes, and the rating estimate — a station-estimated household rating, never negative — feeds both order pricing and post-buy projection, and later anchors the comparable-or-better make-good rule of §3.6. The `is_political_window` flag, defaulting to `false`, marks the program as falling inside a declared political window, where lowest-unit-charge and political-priority rules apply. The program grid can be listed with optional `daypart_code` and `airs_weekday` filters, and the lines buying any given program can be read back through the program's order-line listing.

Against the grid, a `TrafficManager` opens broadcast weeks. Each week is identified by the `week_start_date` of its opening Monday and begins life in `OPEN` status, accepting placements. Later, the week moves to `LOCKED` when a log day inside it is finalized and to `CLOSED` when every log day inside it has been reconciled — both transitions are system-driven and are described with the log workflows in §3.7 and §3.8. Weeks can be listed with an optional `status` filter.

Inside an `OPEN` week, break inventory is carved one avail unit at a time. Creating a unit names the `program_id` whose break it describes, the `air_date` on which it airs, the `break_position` — the ordinal commercial break inside the program, where 1 is the first break — and the `total_seconds` of sellable time in that break. The air date must fall inside the owning week and its weekday must equal the program's `airs_weekday`; a mismatch in either direction is rejected with `ERR_DATE_WINDOW`. The break position must be at least 1, and the total seconds must be positive. During a political window, the unit may also carry `reserved_political_seconds`, which defaults to 0, must never be negative, and must never exceed the unit's `total_seconds`. Creation initializes both booked-second counters of §2.6 to zero. Avail units can be browsed per week, or queried across weeks with optional `program_id`, `avail_week_id`, and `air_date` filters; reading a single unit returns the live booked-second counters alongside its declared capacity.

### 3.3. Copy Registration and Clearance

Spots cannot air without cleared copy, and the copy desk — a `CopyCoordinator` — manages that pipeline per advertiser. Registering a copy instruction records the `advertiser_id` it belongs to, its `length_seconds`, and an optional `rotation_weight`. Copy length must be one of 15, 30, 60, or 120 seconds, and it must equal the `spot_length_seconds` of any line the copy is expected to rotate on — a length mismatch at rotation time is a reference mismatch surfaced per §3.7. The rotation weight expresses the copy's relative airing share among the advertiser's cleared copy of the same length; it must be at least 1 and defaults to 1 when omitted.

Copy arrives in `PENDING` status — received by traffic but not yet cleared for air. Clearing moves it to `RECEIVED`, and only `RECEIVED` copy is eligible for the rotation that runs at log finalization. Withdrawal moves copy from either `PENDING` or `RECEIVED` to the terminal `EXPIRED` status, with one guard: copy that a finalized log still depends on cannot be withdrawn. Specifically, expiring `RECEIVED` copy is rejected with `ERR_INVALID_STATE` while any `FINALIZED` log day references that copy through a spot still in `SCHEDULED` status. Each clearance or withdrawal advances the copy instruction's `version`. An advertiser's copy can be listed with optional `status` and `length_seconds` filters, and the set of spots a given copy instruction has been assigned to can be read back through the copy's spot listing.

### 3.4. Order Entry, Lines, and the Approval Pipeline

A buy starts as an order in `DRAFT`. A `SalesRep` creates it with the buying `advertiser_id`, a `flight_start_date`, and a `flight_end_date`; the flight end is inclusive and must not precede the flight start, else the create is rejected with `ERR_DATE_WINDOW`. A new order carries a `gross_budget_cents` of zero and a `revision_no` of zero.

Lines give the order substance. While the order is in `DRAFT` or `REVISED`, the `SalesRep` adds lines naming the `program_id` being bought, the `weeks_requested`, the `spots_per_week`, the `spot_length_seconds`, the negotiated `gross_rate_cents` per spot, and a `guaranteed_rating`. Weeks requested counts consecutive broadcast weeks beginning with the week containing the order's flight start, and must be at least 1; spots per week must also be at least 1. Spot length must be one of 15, 30, 60, or 120 seconds, the gross rate must be positive, and the guaranteed rating must not be negative — a guarantee of 0 means the line carries no audience guarantee at all. Violations of these field constraints are rejected with `ERR_INVALID_REQUEST`. Each line begins `ACTIVE`. The order's `gross_budget_cents` is maintained automatically: it is the sum over the order's non-cancelled lines of the line's `gross_rate_cents` multiplied by its `spots_per_week` multiplied by its `weeks_requested`, recomputed every time a line is added or cancelled. Both line operations also advance the order's `version`. A single line can be cancelled while the order is in `DRAFT` or `REVISED` and the line itself is still `ACTIVE` — cancelling a line in any other state, including one already `CANCELLED`, is rejected with `ERR_INVALID_STATE`. On cancellation the line moves to `CANCELLED`, its spots still in `PENDING_PLACEMENT`, `PREEMPTED`, or `MAKE_GOOD_OFFERED` are cancelled outright, its `SCHEDULED` spots whose air dates are not yet locked into a finalized log are cancelled with their booked seconds released from the affected avail units, and the budget is recomputed. Lines can be browsed per order — and spots per line — with optional `status` filters, and an order's full roster is also reachable through the advertiser's order listing with `status` filtering.

Submission moves the order from `DRAFT` to `SUBMITTED`, and later from `REVISED` back to `SUBMITTED` in the revision loop. An order with no `ACTIVE` line cannot be submitted; the attempt is rejected with `ERR_INVALID_STATE`.

Approval is the pivot of the whole pipeline, and it belongs to the `TrafficManager`. The approval request must carry `expected_order_version` per §2.8, and a mismatch with the order's current `version` is rejected with `ERR_STALE_ORDER_VERSION`. The credit rule of §3.1 is then applied: the advertiser's outstanding exposure — the summed `gross_budget_cents` of its `APPROVED` and `COMPLETED` orders — plus this order's `gross_budget_cents` must not exceed the advertiser's `credit_limit_cents`, or approval is rejected with `ERR_CREDIT_LIMIT`; a total exactly equal to the limit passes. On approval, the system spawns the order's entire spot inventory: for each `ACTIVE` line, `weeks_requested` multiplied by `spots_per_week` spot rows, each beginning in `PENDING_PLACEMENT` and recording its owning line through `order_line_id`. Every spawned spot's `spot_class` is fixed at creation — `POLITICAL` when the advertiser's `product_category` is `POLITICAL`, otherwise `COMMERCIAL` — and never changes thereafter. Approval, like every order action, advances the order's `version`.

An order that should not proceed can be rejected by the `TrafficManager`, returning it from `SUBMITTED` to `DRAFT`. Revision is the heavier operation: a `SalesRep` can pull an `APPROVED` order back to `REVISED`, but only while no spot of the order has reached `AIRED`; if any spot has aired, the revision is rejected with `ERR_INVALID_STATE`. Revision tears down the un-aired inventory — every spot in `PENDING_PLACEMENT`, `PREEMPTED`, or `MAKE_GOOD_OFFERED` is set to `CANCELLED`, and every `SCHEDULED` spot whose `scheduled_air_date` is not covered by a `FINALIZED` or `RECONCILED` log day — whether no log day exists for that date or it is still in `DRAFT` — is likewise set to `CANCELLED`, with the line's `spot_length_seconds` released from the corresponding avail unit's booked counter for the spot's class bucket. Spots whose air date is covered by a `FINALIZED` or `RECONCILED` log day are left untouched, because those logs are already locked. The order's `revision_no` increments by one on each return to `REVISED`, and its `version` advances as well.

Cancellation follows parallel rules. From `DRAFT`, `SUBMITTED`, or `REVISED`, a `SalesRep` may cancel unconditionally. From `APPROVED`, cancellation requires that no spot of the order has aired — again rejected with `ERR_INVALID_STATE` otherwise — and applies the same spot teardown as revision: spots in `PENDING_PLACEMENT`, `PREEMPTED`, or `MAKE_GOOD_OFFERED` are cancelled, and `SCHEDULED` spots on non-finalized log dates are cancelled with their booked seconds released. `CANCELLED` is terminal, as is `COMPLETED`.

Completion belongs to the system, not to any role. When every spot of an `APPROVED` order has reached a terminal state — `AIRED` or `CANCELLED` — and the order's `flight_end_date` has passed the current logical clock, the order transitions to `COMPLETED`. This completion sweep runs whenever the logical clock is advanced per §2.5: orders whose flight end falls strictly before the new clock date and whose spots are all terminal are completed at that moment.

### 3.5. Placing Spots: Headroom, Separation, and Version Guards

Placement is the `TrafficManager`'s core craft: taking a spot in `PENDING_PLACEMENT` — or a make-good spot in `MAKE_GOOD_OFFERED` — and committing it to a specific break. The placement request names the target `avail_unit_id` and must carry `expected_avail_unit_version` per §2.8; a mismatch with the unit's current `version` is rejected with `ERR_STALE_AVAIL_VERSION`, because another placement or preemption against the same unit has advanced it and the client's headroom arithmetic no longer reflects reality.

Four structural preconditions guard every placement before capacity is even considered. The spot's owning order must be `APPROVED`, and the owning week must still be `OPEN` — a week locked by log finalization rejects new placements with `ERR_INVALID_STATE`. The target unit's air date must lie within the order's flight window, start and end inclusive, else `ERR_DATE_WINDOW`. And the unit must belong to the same program the line buys — a unit whose `program_id` differs from the line's `program_id` is rejected with `ERR_REFERENCE_MISMATCH`.

Capacity is then checked per class, using the counters of §2.6. A `POLITICAL` candidate may use any free second in the break: it is accepted when its duration is no greater than the break's `total_seconds` minus its `booked_political_seconds` minus its `booked_commercial_seconds`. A `COMMERCIAL` candidate is fenced out of the political reserve: it is accepted only when the unit's `booked_commercial_seconds` plus the candidate's duration stays at or below the break's `total_seconds` minus its `reserved_political_seconds`. Political bookings never consume commercial capacity — political spill beyond the reserve leaves the commercial ceiling intact, and the reserve fences commercial bookings only. The boundary is inclusive in both branches: a duration exactly equal to the remaining capacity succeeds, and one second more fails. When a commercial placement would fit only by dipping into the reserved political seconds, the rejection is `ERR_POLITICAL_RESERVE`; when capacity is exhausted outright, the rejection is `ERR_AVAIL_OVERFLOW`.

The last placement gate is commercial separation, evaluated after headroom and in both directions — candidate against occupants and occupants against candidate. Within a single break, two spots whose advertisers share a `product_category` may not air adjacently: at least one other spot must stand between them in the break's airing order. Airing order is derived by sorting the break's `SCHEDULED` spots by `created_at` ascending — creation order is the fixed tie-break, and the spot `id` is never consulted — and the candidate is evaluated as if appended at the last position, immediately after the final occupant. Numbering positions from 1, the placement is accepted only when every same-category occupant sits more than one position away from the candidate; any same-category pair at adjacent positions rejects the placement with `ERR_SEPARATION_VIOLATION`.

A successful placement writes the spot's `avail_unit_id`, copies the unit's air date into the spot's `scheduled_air_date`, adds the line's `spot_length_seconds` to the unit's booked counter for the spot's class bucket, and advances both the spot's `version` and the avail unit's `version`. Make-good placements follow all of the above with one additional gate, described with the make-good cycle in §3.6.

### 3.6. Preemption and the Make-Good Cycle

Preemption pulls a `SCHEDULED` spot out of its break before air. A `TrafficManager` may preempt only while the spot's `scheduled_air_date` is not yet covered by a `FINALIZED` or `RECONCILED` log day — a spot locked into a finalized log cannot be manually preempted, and the attempt is rejected with `ERR_INVALID_STATE`; misses there surface at reconciliation instead. The request supplies a `preempt_reason`, which must be one of `POLITICAL_PRIORITY`, `OVERSOLD`, or `NEWS_OVERRIDE`; a spot's reason field otherwise holds `NONE`, its value until any preemption occurs. Political-priority preemption is itself fenced: it may target only `COMMERCIAL` spots, because political spots cannot be preempted for political priority — attempting it against a `POLITICAL` spot is rejected with `ERR_POLITICAL_RESERVE`. Preemption records the supplied reason on the spot, moves it from `SCHEDULED` to `PREEMPTED`, releases the line's `spot_length_seconds` from the unit's booked counter for the spot's class bucket, and advances both the spot's and the avail unit's `version`. No make-good row is created at this step.

Preemption also previews the station's exposure. Because a manual preemption is discovered while the covering log is still in `DRAFT`, it posts a provisional discrepancy credit at the early tier of §3.8 — the base price of the missed spot with no penalty — immediately against the order's ledger. The heavier late tier applies only when the failure is discovered at reconciliation.

Make-goods give the advertiser a replacement airing. Offering a make-good against a `PREEMPTED` spot creates a new spot row on the same order line, in `MAKE_GOOD_OFFERED` status, carrying the same `spot_class` as the original and pointing back at it through `make_good_of_spot_id`. Only one outstanding make-good may exist per preempted spot: if another spot already references the same original through `make_good_of_spot_id` and stands in `MAKE_GOOD_OFFERED` or `SCHEDULED`, the offer is rejected with `ERR_AVAIL_OVERFLOW`. The offer also touches the originating preempted spot as a side effect: its `version` advances and its `updated_at` refreshes, though none of its other fields change. The offered make-good is then placed through the ordinary placement flow of §3.5 — same headroom, same separation, same version guard — evaluated against its own line, with one additional gate: the comparable-or-better rule. A make-good must target an avail unit whose program's `rating_estimate` is at least the `rating_estimate` of the program whose unit the original spot was preempted from; a downgrade is rejected with `ERR_REFERENCE_MISMATCH`. When the original spot was never placed and has no originating unit, the rating comparison is skipped.

The advertiser's side of the cycle belongs to the `SalesRep`, who may decline an offered make-good, moving it from `MAKE_GOOD_OFFERED` to `CANCELLED`. When the originating preempted spot has no other make-good outstanding in `MAKE_GOOD_OFFERED` or `SCHEDULED`, no further action is taken on it: the preempted spot simply remains `PREEMPTED` until the order completion sweep of §3.4. The make-goods created for any preempted spot can be read back through the original spot's make-good listing.

### 3.7. Log Finalization and Copy Rotation

The daily log is where spots become a broadcast. A `TrafficManager` creates a log day inside a broadcast week by supplying its `log_date`, which must fall inside the owning week or the create is rejected with `ERR_DATE_WINDOW`. Each log day begins in `DRAFT`, and a week's log days can be listed with an optional `status` filter.

Finalization locks the log. A `TrafficManager` finalizes a `DRAFT` log day only while its `log_date` is today or in the future relative to the logical clock — finalizing a past log is rejected with `ERR_DATE_WINDOW`. Every spot scheduled on that date must also have resolvable copy: for each such spot, at least one of its advertiser's copy instructions must be in `RECEIVED` status with a `length_seconds` equal to the spot's line length. When the advertiser of a scheduled spot holds no `RECEIVED` copy at all, finalization fails with `ERR_COPY_NOT_RECEIVED`; when the advertiser does hold `RECEIVED` copy but none whose `length_seconds` equals the line's length, the failure is a reference mismatch and surfaces as `ERR_REFERENCE_MISMATCH`.

For each scheduled spot, finalization then selects exactly one copy by deterministic weighted round-robin over air history. The candidates are the advertiser's `RECEIVED` copy instructions whose `length_seconds` matches the line's `spot_length_seconds`. Each candidate's score is its times-used count divided by its `rotation_weight`, where times-used counts every spot — of any status — whose `copy_instruction_id` referenced that copy at the moment the current finalize run began: the counts are frozen in a snapshot taken as the run starts, so copy assignments written earlier in the same run do not alter the scores of spots finalized later in that run, while assignments from prior runs count normally. The lowest score wins, ties break toward the candidate with the earliest `created_at`, and scores are compared exactly as rational numbers by cross-multiplication, never as rounded floats. The winning copy's identifier is written to the spot's `copy_instruction_id`, and a spot's copy assignment remains visible through the copy instruction's spot listing.

Finalizing a log day also locks its owning week: the week's status moves from `OPEN` to `LOCKED`, freezing new placements into the week per §3.5, and the week's `version` advances alongside the log day's. A second finalization, or any action on a log day that has moved past the state the action requires, is rejected with `ERR_INVALID_STATE`.

### 3.8. As-Run Reconciliation, Credits, and the Post-Buy Report

Reconciliation closes the loop between what was scheduled and what actually aired. A `BillingClerk` reconciles a `FINALIZED` log day by posting its as-run entries: the payload's `entries` must contain exactly one entry per spot in `SCHEDULED` status whose `scheduled_air_date` equals the log day's date — no missing spots and no extras, else the reconcile is rejected with `ERR_RECONCILE_MISMATCH`. Each entry reports the `spot_id`, whether it `aired`, and — whenever `aired` is true — the measured `actual_rating`, which must not be negative; an `actual_rating` supplied on a not-aired entry is accepted, held to the same non-negative rule, and stored with the entry. An entry claiming a spot aired without supplying its `actual_rating` is likewise rejected with `ERR_RECONCILE_MISMATCH`. Accepted entries are stored as append-only `AsRunEntry` rows carrying their owning `log_day_id`, and they remain readable per log day and per spot.

Each reported spot then transitions per its outcome. A spot reported aired moves from `SCHEDULED` to `AIRED`. A spot reported not aired is treated as a miss discovered at air time: it moves from `SCHEDULED` to `PREEMPTED`, its `preempt_reason` is set to `OVERSOLD`, the line's `spot_length_seconds` is released from the unit's booked counter for its class bucket, and a discrepancy credit is posted. Both outcomes advance the spot's `version`.

The discrepancy credit prices a missed spot. Its base is the line's `gross_rate_cents`, and a penalty percentage is applied on top according to how late the failure was discovered. A failure discovered at reconciliation — after the log had been finalized — carries a penalty of twenty-five percent of the base. A failure discovered by manual preemption while the covering log was still in `DRAFT` carries no penalty at all, which is the provisional credit already posted in §3.6. The credit amount is the base multiplied by one plus the penalty percentage, then truncated down to whole cents — multiplication first, the floor applied once at the end, with no intermediate rounding. The reconciliation-time tier therefore produces a strictly larger credit than the provisional tier for the same spot price.

Audience delivery is scored in parallel for every aired spot on a guaranteed line — any line whose `guaranteed_rating` is greater than zero. For each such spot, booked impressions are the `guaranteed_rating` multiplied by one thousand, and delivered impressions are the spot's `actual_rating` multiplied by the same one thousand weighting. The spot's deficit is the amount by which booked exceeds delivered, floored at zero and kept to three decimal places; under the station's default per-spot-strict method, over-delivery on one spot never offsets under-delivery on another. The line's post-buy deficit total is the exact sum of its aired spots' deficits, and the audience-deficiency units owed on the line are that total multiplied by the number of spots the line aired, rounded up to a whole number of ADU. An agency-negotiated alternative, the week-averaged method, averages the actual ratings across the line's aired spots inside a single broadcast week before comparing to the guarantee: the weekly deficit is the amount by which the guarantee exceeds the week's average — floored at zero — multiplied by the count of the line's aired spots that week, and it is likewise kept to three decimal places, rounded half up. Under week-averaging, over-delivery does offset under-delivery within the same week, but different weeks never offset each other. Spots that were preempted, cancelled, or never aired are excluded from both methods; only `AIRED` spots count.

The post-buy report assembles all of this per order, on demand, for `SalesRep`, `TrafficManager`, `BillingClerk`, and `StationAdmin` readers. An optional `method_variant` query parameter selects the audience-shortfall method: the value `per_spot_strict` selects the default per-spot-strict method and is assumed when the parameter is omitted or empty, and `week_averaged` selects the week-averaged alternative; any other value is rejected with `ERR_INVALID_REQUEST`. The report responds with the `order_id`, the selected `method_variant` echoed back, a per-line `lines` breakdown, and three credit figures: `discrepancy_credit_cents`, `shortfall_credit_cents`, and `order_credit_cents`. The `lines` breakdown covers every line of the order regardless of status, in creation order; each entry carries `order_line_id`, `status`, `guaranteed_rating`, `aired_spot_count` (the count of the line's `AIRED` spots), `average_actual_rating` (the mean of those spots' measured ratings, rounded to three decimal places, or null when the line has no aired spots), `post_buy_deficit_points` (the line's deficit rollup under the selected method), `adu_owed`, `cpp_cents` (the line's `gross_rate_cents` divided by its `guaranteed_rating`, or null when the guarantee is zero), and `shortfall_credit_cents`. The order-level credit is computed as a waterfall in a pinned order. The discrepancy bucket comes first: the sum of the discrepancy credits already posted for the order's missed spots. The shortfall bucket comes second: for each line, the line's deficit rollup under the selected method — the sum of per-spot deficits under the strict method, or the sum of per-week deficits under week-averaging — is valued at the line's average paid cost per point, computed as the line's `gross_rate_cents` divided by its `guaranteed_rating`, and the product is truncated down to whole cents per line, the floor applied after the multiplication and per line rather than on the order total. Lines with a `guaranteed_rating` of zero contribute nothing to the shortfall bucket. The order's total credit is the sum of the two buckets.

Reconciliation has one final cascade: when every log day of the owning week has reached `RECONCILED`, the week's status moves from `LOCKED` to the terminal `CLOSED`, its `version` advancing with the transition, and the week is fully settled.

## 4. Endpoint Definitions

Operations that create a new resource — an advertiser, a program, a broadcast week, an avail unit, a log day, an order, an order line, a copy instruction, or a make-good spot — return `201 Created`. Operations that modify an existing resource's state, including all workflow actions and the clock setter, return `200 OK`, as do all reads. Request and response payloads for each operation are defined by the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/traffic/advertisers` | Create an advertiser | SalesRep |
| GET | `/traffic/advertisers` | List advertisers | SalesRep, TrafficManager, CopyCoordinator, BillingClerk, StationAdmin |
| GET | `/traffic/advertisers/{id}` | Get one advertiser | SalesRep, TrafficManager, CopyCoordinator, BillingClerk, StationAdmin |
| GET | `/traffic/advertisers/{id}/orders` | List orders of an advertiser | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/advertisers/{id}/copy-instructions` | List copy instructions of an advertiser | SalesRep, TrafficManager, CopyCoordinator |
| POST | `/traffic/programs` | Create a program | TrafficManager |
| GET | `/traffic/programs` | List programs | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/programs/{id}` | Get one program | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| POST | `/traffic/avail-weeks` | Open a broadcast week | TrafficManager |
| GET | `/traffic/avail-weeks` | List broadcast weeks | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/avail-weeks/{id}` | Get one broadcast week | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| POST | `/traffic/avail-weeks/{id}/avail-units` | Create an avail unit (break inventory) inside a week | TrafficManager |
| GET | `/traffic/avail-weeks/{id}/avail-units` | List avail units of a week | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/avail-units/{id}` | Get one avail unit including live booked-second counters | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/avail-units` | Filtered list of avail units across weeks | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/programs/{id}/order-lines` | List order lines buying a program | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/copy-instructions/{id}/spots` | List spots assigned a copy instruction | SalesRep, TrafficManager, CopyCoordinator |
| GET | `/traffic/spots/{id}/make-goods` | List make-good spots created for a preempted spot | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/spots/{id}/as-run-entries` | List as-run entries posted for a spot | TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/avail-weeks/{id}/log-days` | List log days of a week | TrafficManager, BillingClerk, StationAdmin |
| POST | `/traffic/avail-weeks/{id}/log-days` | Create a log day inside a week | TrafficManager |
| POST | `/traffic/orders` | Create an order in DRAFT | SalesRep |
| GET | `/traffic/orders` | List orders | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/orders/{id}` | Get one order | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| POST | `/traffic/orders/{id}/lines` | Add an order line (DRAFT or REVISED orders only) | SalesRep |
| GET | `/traffic/orders/{id}/lines` | List lines of an order | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/order-lines/{id}` | Get one order line | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| POST | `/traffic/order-lines/{id}/cancel` | Cancel a single line; cancels its non-aired spots and frees booked seconds on DRAFT logs | SalesRep |
| POST | `/traffic/orders/{id}/submit` | Submit an order for approval | SalesRep |
| POST | `/traffic/orders/{id}/approve` | Approve a submitted order; spawns its spot inventory | TrafficManager |
| POST | `/traffic/orders/{id}/reject` | Reject a submitted order back to DRAFT | TrafficManager |
| POST | `/traffic/orders/{id}/revise` | Pull an APPROVED order back to REVISED; cancels un-aired spot inventory | SalesRep |
| POST | `/traffic/orders/{id}/cancel` | Cancel an order | SalesRep |
| GET | `/traffic/orders/{id}/post-buy` | Computed post-buy report: delivered vs guaranteed ratings, ADU owed, credits | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| POST | `/traffic/copy-instructions` | Register copy for an advertiser (starts PENDING) | CopyCoordinator |
| GET | `/traffic/copy-instructions/{id}` | Get one copy instruction | SalesRep, TrafficManager, CopyCoordinator |
| POST | `/traffic/copy-instructions/{id}/receive` | Clear copy for air | CopyCoordinator |
| POST | `/traffic/copy-instructions/{id}/expire` | Withdraw copy | CopyCoordinator |
| GET | `/traffic/spots/{id}` | Get one spot | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/order-lines/{id}/spots` | List spots of an order line | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/avail-units/{id}/spots` | List spots scheduled into an avail unit | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| GET | `/traffic/log-days/{id}/as-run-entries` | List as-run entries posted against a log day | TrafficManager, BillingClerk, StationAdmin |
| POST | `/traffic/spots/{id}/place` | Place a PENDING_PLACEMENT or MAKE_GOOD_OFFERED spot into an avail unit | TrafficManager |
| POST | `/traffic/spots/{id}/preempt` | Preempt a scheduled spot (DRAFT log only); frees seconds and marks the reason | TrafficManager |
| POST | `/traffic/spots/{id}/offer-make-good` | Create a make-good spot for a preempted spot | TrafficManager |
| POST | `/traffic/spots/{id}/decline-make-good` | Decline an offered make-good | SalesRep |
| GET | `/traffic/log-days/{id}` | Get one log day | SalesRep, TrafficManager, BillingClerk, StationAdmin |
| POST | `/traffic/log-days/{id}/finalize` | Finalize a log day: fixes spot order, assigns copy by rotation, locks the week | TrafficManager |
| POST | `/traffic/log-days/{id}/reconcile` | Post as-run entries; airs or preempts reported spots, posts credits and shortfall | BillingClerk |
| POST | `/traffic/_clock/set_current_utc` | Set the server's logical clock and run the order completion sweep | StationAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DATE_WINDOW` | 422 |
| `ERR_REFERENCE_MISMATCH` | 422 |
| `ERR_POLITICAL_RESERVE` | 422 |
| `ERR_AVAIL_OVERFLOW` | 422 |
| `ERR_SEPARATION_VIOLATION` | 422 |
| `ERR_COPY_NOT_RECEIVED` | 422 |
| `ERR_RECONCILE_MISMATCH` | 422 |
| `ERR_CREDIT_LIMIT` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_STALE_AVAIL_VERSION` | 412 |
