# Cranberry Coop API — Product Requirements Document

## 1. Introduction

A grower-owned cranberry marketing cooperative runs its entire harvest campaign on a shared calendar: growers declare acreage and expected yields for each bog, field officers supervise wet and dry harvest windows and cold-night frost protection, receiving stations weigh and grade incoming fruit, and the pool desk books provisional advances against deliveries before settling each marketing pool and cutting patronage distributions. This document specifies the HTTP API that coordinates that campaign end to end, from the day a marketing season is opened through the day the last distribution is marked paid.

The design rests on a few deliberate commitments. Member delivery quotas are computed under two parallel variants — an acreage-baseline view and an approved-estimate view — so that the co-op always knows both what the land would predict and what the growers have sworn to. Money flows through marketing pools as a ledger: provisional advances recorded at acceptance are later reconciled against a final pool settlement, with the co-op's retain and a rounding residual accounted for explicitly. Several lifecycles are cyclic rather than linear — a delivery's grade can be disputed and re-graded, a closed pool can be reopened for late adjustments, and a bog cycles through renovation and replanting back into production — so the API treats state transitions, their preconditions, and their compensating side effects as first-class parts of the contract.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across every resource and endpoint in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly five roles, spelled precisely as follows: `CoopAdmin`, `GrowerMember`, `FieldOfficer`, `StationOperator`, and `PoolManager`. A request missing either header, or presenting a role string outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted on the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN`.

Two of the five roles are **entity-backed**: their `X-User-ID` is the `id` of a persisted resource, and ownership comparisons use that identifier. When `X-User-Role` is `GrowerMember`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member — bogs, yield estimates, harvest tickets, and deliveries — compare the resource's `member_id` field to `X-User-ID`, and a grower may act only on their own records. When `X-User-Role` is `StationOperator`, `X-User-ID` is the `id` of the acting `ReceivingStation`; receiving and grading a delivery compares the delivery's `receiving_station_id` to `X-User-ID`, so an operator may weigh and grade only deliveries booked at their own station.

The remaining three roles carry an **opaque** identifier not tied to any persisted entity. When `X-User-Role` is `CoopAdmin`, `FieldOfficer`, or `PoolManager`, `X-User-ID` is an operator identifier that the server does not compare against any entity's `id`; authorization for these roles is purely a matter of role-to-endpoint permission.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — seasons, members, quotas, bogs, yield estimates, receiving stations, harvest tickets, frost events, pools, deliveries, and patronage distributions — carries the same four system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): starts at its initial value on creation and increments by exactly 1 on every mutation.

A mutation is any change to the resource, including changes driven indirectly: a quota recomputed because an estimate was flagged, a pool whose totals grew because a delivery was accepted, and a quota locked because the season closed are all mutations that refresh `updated_at` and increment `version` on the affected resource, even though the client never wrote to that resource directly.

### 2.5. Precision, Rounding, and Measurement Conventions

All barrel quantities and all monetary amounts in the system are computed with decimal arithmetic and stored rounded half-up to exactly 2 decimal places — this covers `net_barrels`, `weighted_barrels`, quota figures such as `base_quota_barrels` and `baseline_quota_barrels`, the split quantities `quota_applied_barrels` and `over_quota_barrels`, every `advance_amount`, and all settlement money (`gross_amount`, `retain_amount`, `cash_amount`, and the pool-level `coop_equity_residual`). Per-barrel pool rates are the one exception to two-decimal rounding: the `final_rate_per_weighted_barrel` computed at settlement is rounded half-up to 4 decimal places, while input rate fields such as `provisional_advance_rate_per_barrel` preserve the precision supplied by the client. Grading scores (`color_score`, `firmness_score`) and `foreign_matter_pct` are compared exactly at their stated thresholds, with no rounding applied before comparison. Monetary values and computed quantities are returned in response bodies as JSON numbers, never strings.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each requiring a non-optional expected-version field in the request body:

- Updating a pool's provisional advance rate (`PATCH /coop/pools/{id}`) requires `expected_pool_version`, carrying the pool `version` the client last observed.
- Manually overriding a member quota (`PATCH /coop/quotas/{id}`) requires `expected_quota_version`, carrying the quota `version` the client last observed.
- Settling a closed pool (`POST /coop/pools/{id}/settle`) requires `expected_pool_version` in the same sense.

If the supplied value does not match the entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Staleness can arise without the client ever writing: quota recomputations triggered by estimate approvals, frost-damage flagging, or bog renovation transitions each increment the quota's `version`, and a pool's `version` advances on rate updates, on delivery acceptance tagging, and on void compensation — so any previously observed version may already be behind. Endpoints other than the three listed above do not take a version field.

### 2.7. The Logical Clock and the Expiry Sweep

The server keeps a logical UTC clock used for time-dependent housekeeping. Before any clock-setting call is made, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A `CoopAdmin` advances it through an admin-only test-driving capability that accepts a `to_iso8601` instant and reports the resulting `current_utc`. Setting the clock triggers an expiry sweep: every harvest ticket still in `REQUESTED` status whose `window_start` lies before the new current time is moved to `EXPIRED`.

### 2.8. Validation Order and Reference Resolution

A request that would fail several checks is always rejected by the earliest applicable band, and the bands are evaluated in this fixed order:

1. **Request shape** — required fields present, types well-formed, enum members valid, scalar ranges enforced (strictly positive `acres`, `sprinkler_demand_gpm`, `daily_capacity_barrels`, `expected_barrels`, and `estimated_barrels`; grading scores within 0 to 10; non-negative `foreign_matter_pct`; `retain_pct` between 0 and 1 inclusive; non-negative rates; parseable dates). Violations yield `ERR_VALIDATION`.
2. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is declared; otherwise `ERR_UNAUTHENTICATED`.
3. **Authorization and ownership** — the role is permitted on the endpoint and entity-backed ownership checks pass; otherwise `ERR_FORBIDDEN`.
4. **Existence** — path identifiers and body-referenced ids (such as `season_id`, `bog_id`, `receiving_station_id`, and `harvest_ticket_id`) resolve to live records, validated left to right so the first missing reference surfaces; otherwise `ERR_NOT_FOUND`.
5. **Optimistic concurrency** — on the three OCC-guarded writes, the expected version matches; otherwise `ERR_STALE_VERSION`.
6. **State legality and uniqueness** — the target resource is in a state from which the requested transition is defined, including terminal lockdown (`ERR_INVALID_STATE`); duplicate-creation uniqueness for the season `year`, the member `member_code`, the pool code within a season, and one estimate per bog-and-season pair is checked in this same band against live records (`ERR_DUPLICATE_SEASON_YEAR`, `ERR_DUPLICATE_MEMBER_CODE`, `ERR_DUPLICATE_POOL_CODE`, `ERR_DUPLICATE_ESTIMATE`).
7. **Window sanity and season alignment** — `window_start` strictly before `window_end` (`ERR_INVALID_WINDOW`), and harvest-ticket windows and delivery appointment dates lying within the season's harvest window (`ERR_WINDOW_OUTSIDE_SEASON`).
8. **Resource occupation conflicts** — harvest-window overlap on a bog, station aggregate daily capacity, and frost-versus-flood water conflicts (`ERR_HARVEST_WINDOW_OVERLAP`, `ERR_STATION_CAPACITY_EXCEEDED`, `ERR_WATER_SCHEDULE_CONFLICT`).
9. **Referenced-entity state compatibility** — checked in this order: season status first (season `OPEN` for delivery creation and acceptance; season `SETUP` or `OPEN` for pool, estimate, and ticket creation), then bog `ACTIVE` where required, then station existence and harvest-ticket consistency, then the quota lock (`ERR_SEASON_NOT_OPEN`, `ERR_BOG_NOT_ACTIVE`, `ERR_TICKET_INVALID`, `ERR_QUOTA_LOCKED`).
10. **Fiscal pool and settlement rules** — pool availability at acceptance or void, and settlement money sanity (`ERR_POOL_NOT_OPEN`, `ERR_OVER_QUOTA_POOL_UNAVAILABLE`, `ERR_SETTLEMENT_INPUT_INVALID`).

### 2.9. Season–Pool State Coupling and Quota Locking

A season and its marketing pools form a coupled hierarchy in which the season's status is derived from the states of its pools, without any client writing to the season directly. When every pool of an `OPEN` season has reached `CLOSED` or `SETTLED` — and at least one pool exists — the season automatically advances from `OPEN` to `HARVEST_CLOSED`; as part of that transition every member quota of the season is locked (`quota_locked` becomes `true`), and each such locking mutation increments the affected quota's `version` by 1. Reopening is symmetric: when a pool of a `HARVEST_CLOSED` season cycles back to `OPEN`, the season automatically reverts from `HARVEST_CLOSED` to `OPEN` and the quota locks are cleared, again incrementing each affected quota's `version` by 1. Finally, when every pool of the season has reached `SETTLED`, the season automatically advances from `HARVEST_CLOSED` to `SETTLED`, its terminal state. While a season is `HARVEST_CLOSED` or later, manual quota overrides are refused and all quota recomputation is skipped — the locked figures are the ones settlement will honor.

## 3. Business Logic & Workflows

### 3.1. Season Setup and Member Enrollment

A `CoopAdmin` opens a campaign by creating the **Season**: the four-digit marketing `year`, the inclusive `harvest_window_start` and `harvest_window_end` dates that bound all harvest activity, and the `baseline_barrels_per_acre` used both by the acreage-baseline quota variant and as the per-bog fallback for acreage without an approved estimate. The `year` must be unique across all seasons — a second season for the same year is rejected with `ERR_DUPLICATE_SEASON_YEAR` — and a `harvest_window_end` earlier than `harvest_window_start` is rejected as malformed with `ERR_VALIDATION`. A new season begins in `SETUP`.

Growers join through member registration, also a `CoopAdmin` duty. Each **Member** carries a unique `member_code` (duplicates rejected with `ERR_DUPLICATE_MEMBER_CODE`) and a display `full_name`, and starts life `PENDING`. The member lifecycle is a simple loop administered by `CoopAdmin` via a transition request naming the target `to`: `PENDING → ACTIVE`, `ACTIVE → SUSPENDED`, `SUSPENDED → ACTIVE`, and — provided the member has no delivery still in flight in `SCHEDULED`, `RECEIVED`, `GRADED`, or `DISPUTED` status — `ACTIVE → WITHDRAWN`, which is terminal.

Opening the season is the pivotal act. A `CoopAdmin` may open a `SETUP` season only when at least one member has reached `ACTIVE`; the season then moves to `OPEN`, and the system creates one **MemberQuota** per `ACTIVE` member for that season, computing both quota variants at creation time as described in §3.3. Members activated only after the season has opened do not receive a retroactive quota row. Quota rows may be listed with optional `member_id` and `season_id` filters alongside the standard `limit` and `offset` pagination parameters.

### 3.2. Bog Registration and the Renovation Cycle

Each grower's land is registered as a **Bog**. A `GrowerMember` registers their own bog — ownership is taken from the caller's `X-User-ID` — while a `CoopAdmin` registering on a grower's behalf must supply the owning `member_id` explicitly. Registration captures the bog `name`, planted `acres` (strictly greater than zero), the cranberry `variety` (one of `STEVENS`, `BEN_LEAR`, `MULICA_QUEEN`, or `EARLY_BLACK`), the frost-protection `sprinkler_demand_gpm` draw in gallons per minute (a strictly positive integer), and optionally the `frost_damage_threshold_c`, the actual temperature at or below which a completed frost event marks the vines damaged; when omitted, the threshold defaults to -2.0 degrees. A new bog starts `ACTIVE`, and bog listings accept `member_id` and `status` filters.

Renovation is a cycle, not a dead end. The owning grower (or a `FieldOfficer`) may move an `ACTIVE` bog to `RENOVATION_PLANNED`, and may just as freely cancel the plan back to `ACTIVE`. A `FieldOfficer` alone takes the bog from `RENOVATION_PLANNED` to `UNDER_RENOVATION`, later marks it `REPLANTED`, and finally certifies the vines mature by returning it to `ACTIVE`. Two of these steps ripple into quota accounting: entering `UNDER_RENOVATION` removes the bog from the quota input set, triggering a recomputation of the member's quota for every season whose quota is not locked, and the certification back to `ACTIVE` re-adds the bog and recomputes again. Requesting a transition the bog's current status does not define is rejected with `ERR_INVALID_STATE`; a grower touching another member's bog is rejected with `ERR_FORBIDDEN`.

### 3.3. Yield Estimates and the Dual Quota Computation

Before the harvest begins, each grower declares what each bog will bear. A `GrowerMember` submits a **YieldEstimate** naming the `bog_id`, the `season_id`, and a strictly positive `estimated_barrels`; the estimate's `member_id` is copied from the bog's owner at creation. Submission requires the season to be in `SETUP` or `OPEN` (`ERR_SEASON_NOT_OPEN` otherwise), the bog to be `ACTIVE` (`ERR_BOG_NOT_ACTIVE` otherwise), and the grower to own the bog. At most one estimate exists per bog-and-season pair — a second submission for the same pair is rejected with `ERR_DUPLICATE_ESTIMATE`. Estimate listings support `bog_id`, `season_id`, `member_id`, and `status` filters.

Review belongs to the `FieldOfficer`. An estimate arrives `SUBMITTED`; the officer approves it — again requiring the bog to be `ACTIVE`, failing with `ERR_BOG_NOT_ACTIVE` — or flags it for revision. A grower revises a `FLAGGED` estimate by resubmitting with `revised_estimated_barrels`: the estimate returns to `SUBMITTED`, its `estimated_barrels` is replaced by the revised figure, and its `revision_count` increments by 1. Approval and flagging each trigger a recomputation of the owning member's quota, because only `APPROVED` estimates feed the official quota.

The quota itself is computed under **two parallel variants** and both are stored on the MemberQuota. The acreage-baseline variant, stored as `baseline_quota_barrels`, ignores grower declarations entirely: for every one of the member's bogs in `ACTIVE` status (bogs in `RENOVATION_PLANNED`, `UNDER_RENOVATION`, or `REPLANTED` are excluded), multiply the bog's `acres` by the season's `baseline_barrels_per_acre`, round each per-bog product half-up to two decimal places, and sum the rounded products. The approved-estimate variant produces the official `base_quota_barrels`: over the same set of `ACTIVE` bogs, take the bog's `APPROVED` estimate's `estimated_barrels` for the season where one exists and the rounded acreage product as the per-bog fallback where none does (`SUBMITTED` and `FLAGGED` estimates never count), then round the total half-up to two decimal places. Recomputation fires when the season is opened, when an estimate transitions to `APPROVED` or `FLAGGED`, and when a bog moves out of or back into the `ACTIVE` input set — but it is skipped entirely while the quota's `quota_locked` flag is `true`, which the season sets at `HARVEST_CLOSED`.

A `CoopAdmin` may pin a quota manually: the override request carries the desired `base_quota_barrels` together with `expected_quota_version`, stores the value in `base_quota_override`, and recomputes the member's posture. While `base_quota_override` is non-null it wins over any recomputation of the official figure. An override attempted on a locked quota — one whose season has reached `HARVEST_CLOSED` — is rejected with `ERR_QUOTA_LOCKED`, and a stale `expected_quota_version` draws `ERR_STALE_VERSION`.

Two accumulators track delivery against the quota: `delivered_barrels` is the sum of `quota_applied_barrels` over the member's `ACCEPTED`, non-`VOIDED` deliveries of the season, and the quota row's own `over_quota_barrels` is the matching sum of delivery-level overage. The quota's `posture` reads `WITHIN_QUOTA` while `delivered_barrels` is at most `base_quota_barrels`, and flips to `OVER_QUOTA` the moment deliveries exceed it.

### 3.4. Harvest Tickets and Bog Water Scheduling

Harvesting a bog requires an authorized window. A `GrowerMember` requests a **HarvestTicket** for one of their bogs, naming the `bog_id`, the `season_id`, the harvest `method` — `WET` or `DRY` — and the half-open interval from `window_start` to `window_end`; the ticket's `member_id` is copied from the bog. Creation requires the season in `SETUP` or `OPEN`, the bog `ACTIVE`, a `window_start` strictly before `window_end` (`ERR_INVALID_WINDOW` otherwise), and a window that lies entirely within the season's inclusive harvest window (`ERR_WINDOW_OUTSIDE_SEASON` otherwise). The ticket begins `REQUESTED`, and ticket listings accept `bog_id`, `season_id`, `member_id`, `status`, and `method` filters.

One bog cannot host two overlapping live tickets. A new or approving ticket conflicts with any other ticket on the same bog in `REQUESTED` or `APPROVED` status whenever the existing ticket's `window_start` falls before the new window's end and the new window's start falls before the existing ticket's end — half-open interval semantics, under which two windows that merely touch (one's end equal to the other's start) do **not** conflict. The check runs at creation and is re-checked at approval; a conflict is rejected with `ERR_HARVEST_WINDOW_OVERLAP`.

A `FieldOfficer` approves a `REQUESTED` ticket — approval requires the bog still `ACTIVE` (`ERR_BOG_NOT_ACTIVE`) in addition to the fresh overlap check — and later marks an `APPROVED` ticket `COMPLETED`. Cancellation from either `REQUESTED` or `APPROVED` is available to the owning grower or a `FieldOfficer`, moving the ticket to `CANCELLED`. Finally, the clock sweep of §2.7 retires any ticket still `REQUESTED` once its start has passed, moving it to `EXPIRED`. `COMPLETED`, `CANCELLED`, and `EXPIRED` are all terminal.

The `method` matters beyond the harvest itself: a `WET` ticket floods the bog from 24 hours before its `window_start` until its `window_end`, and that flood interval is what frost-protection scheduling must steer around (§3.5). `DRY` tickets occupy no water interval at all.

### 3.5. Frost Protection Events and the Damage Cascade

When a cold night threatens, a `FieldOfficer` declares a **FrostEvent** on a bog: the `bog_id`, the `season_id` identifying the marketing season whose crop is being protected (this drives which estimate the damage cascade targets), the sprinkler window from `window_start` to `window_end` (again `window_start` strictly before `window_end`, else `ERR_INVALID_WINDOW`), and the `forecast_min_temp_c` driving the call. The event starts `DECLARED`; event listings accept `bog_id`, `season_id`, and `status` filters.

Water is the scarce resource. A frost event conflicts — and its creation is rejected with `ERR_WATER_SCHEDULE_CONFLICT` — whenever its window intersects the flood interval of any `WET` harvest ticket on the same bog in `REQUESTED` or `APPROVED` status, where the ticket's flood interval runs from 24 hours before the ticket's `window_start` until the ticket's `window_end`, and intersection means the flood interval's start falls before the frost window's end while the frost window's start falls before the ticket's `window_end`. `DRY` tickets occupy no flood interval and never produce this conflict.

The officer then activates the event (`DECLARED → ACTIVE`), and when the night has passed, completes it by supplying the observed `actual_min_temp_c` — completion without that reading is not permitted. At completion the system computes `damage_flag`: `true` exactly when `actual_min_temp_c` is at or below the bog's `frost_damage_threshold_c`. A damaging completion cascades: if an `APPROVED` yield estimate exists for that bog and the event's season, it transitions automatically from `APPROVED` to `FLAGGED`, which triggers a recomputation of the member's quota excluding that estimate — and if the member's deliveries already exceed the recomputed figure, the quota's `posture` flips to `OVER_QUOTA` as part of the same cascade. An event may instead be abandoned from either `DECLARED` or `ACTIVE`, ending `CANCELLED`; `COMPLETED` and `CANCELLED` are terminal.

### 3.6. Delivery Scheduling, Weigh-In, and Grading

Fruit moves to market as a **Delivery**. A `GrowerMember` schedules an appointment by naming the `season_id`, the `bog_id`, the `receiving_station_id`, the `scheduled_date`, and the strictly positive `expected_barrels` declared for capacity planning; an optional `harvest_ticket_id` links the delivery to its authorizing ticket. Scheduling requires the season to be `OPEN` (`ERR_SEASON_NOT_OPEN` otherwise), the bog to be `ACTIVE` (`ERR_BOG_NOT_ACTIVE` otherwise), and the `scheduled_date` to fall within the season's inclusive harvest window (`ERR_WINDOW_OUTSIDE_SEASON` otherwise). When a `harvest_ticket_id` is supplied, the ticket must be `APPROVED` and must belong to the same bog as the delivery, else the request fails with `ERR_TICKET_INVALID`. The delivering `member_id` is taken from the caller's `X-User-ID`, and the new delivery starts `SCHEDULED`. Delivery listings accept a broad filter set: `member_id`, `season_id`, `bog_id`, `receiving_station_id`, `main_pool_id`, `over_quota_pool_id`, `harvest_ticket_id`, `status`, and `scheduled_date`.

Receiving stations are capacity-limited in the aggregate, not pairwise: the day's load at a station is the sum of `expected_barrels` over all deliveries at that station on the same `scheduled_date` in `SCHEDULED` or `RECEIVED` status, and a new booking is rejected with `ERR_STATION_CAPACITY_EXCEEDED` when that load plus the new `expected_barrels` would exceed the station's `daily_capacity_barrels` — a total exactly equal to the daily capacity is allowed. Stations themselves are registered by a `CoopAdmin` with a `name` and a strictly positive integer `daily_capacity_barrels`.

On the day, the `StationOperator` at the booked station confirms the scale: the request carries `gross_barrels` and `tare_barrels`, and a `tare_barrels` greater than `gross_barrels` is rejected with `ERR_TARE_EXCEEDS_GROSS`. The operator must belong to the delivery's station — the delivery's `receiving_station_id` is compared to `X-User-ID`, with `ERR_FORBIDDEN` on mismatch — and the delivery moves `SCHEDULED → RECEIVED` with `net_barrels` computed as the gross minus the tare, rounded half-up to two decimals.

Grading follows at the same station. The operator records `color_score` and `firmness_score` (each between 0 and 10) and `foreign_matter_pct` (non-negative), and the grade is assigned by a fixed tier ladder. Foreign matter above 6.0 percent rejects the fruit outright before any tier is considered. Otherwise the tiers are tested from the top down: `A` requires color and firmness each at least 8.0 with foreign matter at most 2.0 percent; `B` requires color and firmness each at least 7.0 with foreign matter at most 4.0 percent; `C` requires color and firmness each at least 6.0 with foreign matter at most 6.0 percent; fruit failing all three tiers is `REJECT`. Every boundary is inclusive — scores of exactly 8.0, 8.0, and 2.0 percent earn grade `A`. The grade fixes the `premium_multiplier`: 1.10 for `A`, 1.00 for `B`, 0.90 for `C`, and 0 for `REJECT`; `weighted_barrels` is the `net_barrels` multiplied by that multiplier, rounded half-up to two decimals. A passing grade moves the delivery `RECEIVED → GRADED`; a `REJECT` result moves it to `REJECTED`, which is terminal.

A grower who disagrees with the grade may dispute it: the owning grower (delivery `member_id` matching `X-User-ID`, else `ERR_FORBIDDEN`) moves a `GRADED` delivery to `DISPUTED`, incrementing `dispute_count` by 1. Re-grading from `DISPUTED` records a fresh set of scores through the same station-side grading action, replacing the prior `color_score`, `firmness_score`, and `foreign_matter_pct` and recomputing the grade, multiplier, and weighted barrels; the delivery lands on `GRADED` when the new result passes and on `REJECTED` when it does not.

### 3.7. Acceptance, the Quota Split, and Provisional Advances

Acceptance is the moment fruit becomes money, and it belongs to the `PoolManager`. A graded delivery is accepted only while its season is `OPEN` (`ERR_SEASON_NOT_OPEN` otherwise) and the season's `MAIN` pool is `OPEN` (`ERR_POOL_NOT_OPEN` otherwise). Acceptance then splits the delivery against the member's quota. The remaining headroom is the `base_quota_barrels` minus the `delivered_barrels`, floored at zero; `quota_applied_barrels` is the smaller of the delivery's `net_barrels` and that headroom, and the delivery's `over_quota_barrels` is whatever remains of the net. The boundary is inclusive: when deliveries to date plus this load land exactly on the quota, the delivery is fully in-quota and no overage arises. Whenever `over_quota_barrels` is greater than zero, the season's `OPEN` `OVER_QUOTA` pool must exist — at most one pool of each code exists per season by the uniqueness rule — and its absence rejects the acceptance with `ERR_OVER_QUOTA_POOL_UNAVAILABLE`.

Pool tagging follows the split. The delivery's `main_pool_id` is set to the season's `OPEN` `MAIN` pool, and when overage exists its `over_quota_pool_id` is set to the season's `OPEN` `OVER_QUOTA` pool. The delivery's `weighted_barrels` is divided between the two pools in the same proportion as the barrel split — the in-quota weighted share is the `weighted_barrels` multiplied by the fraction that `quota_applied_barrels` forms of `net_barrels`, and the remainder belongs to the over-quota portion — and the `advance_amount` booked on the delivery is the sum of two independently rounded terms: the in-quota weighted share times the `MAIN` pool's `provisional_advance_rate_per_barrel`, rounded half-up to two decimals, plus the over-quota weighted share times the `OVER_QUOTA` pool's rate, likewise rounded. The member's quota absorbs the delivery (`delivered_barrels` grows by `quota_applied_barrels`, the quota's `over_quota_barrels` grows by the overage, and `posture` is recomputed), and each tagged pool's totals grow by its portion — `accepted_net_barrels` by the barrel portion, `weighted_barrels_total` by the weighted share, `advances_outstanding` by the advance term — with every such pool mutation incrementing that pool's `version`. The delivery arrives at `ACCEPTED`.

Voiding is the exact mirror. A `PoolManager` may void an `ACCEPTED` delivery only while every tagged pool is still `OPEN` (`ERR_POOL_NOT_OPEN` otherwise). The void subtracts precisely the contributions the acceptance recorded: the quota's `delivered_barrels` and `over_quota_barrels` are reduced by the delivery's `quota_applied_barrels` and `over_quota_barrels` with `posture` recomputed, and each tagged pool's `accepted_net_barrels`, `weighted_barrels_total`, and `advances_outstanding` are reduced by exactly this delivery's recorded portions, each pool's `version` incrementing again. The delivery ends `VOIDED`, a terminal state, and its barrels no longer count anywhere.

### 3.8. Pool Lifecycle, Settlement, and Patronage

Pools are the co-op's marketing instruments. A `PoolManager` creates a **Pool** for a season by naming the `season_id`, the pool `code` (`MAIN` or `OVER_QUOTA` — unique per season, duplicates rejected with `ERR_DUPLICATE_POOL_CODE`), the `provisional_advance_rate_per_barrel` paid out at delivery acceptance, and the `retain_pct`, the fraction of gross settlement withheld as the co-op's retain, between 0 and 1 inclusive. Creation requires the season in `SETUP` or `OPEN` (`ERR_SEASON_NOT_OPEN` otherwise), and the pool opens in `OPEN` status with its computed totals — `accepted_net_barrels`, `weighted_barrels_total`, and `advances_outstanding` — all at zero. Pool listings accept `season_id`, `code`, and `status` filters.

While a pool is `OPEN` its advance rate may be revised with the pool's new `provisional_advance_rate_per_barrel` plus `expected_pool_version`; a rate change on a pool that is not `OPEN` is rejected with `ERR_POOL_NOT_OPEN`, a stale version draws `ERR_STALE_VERSION`, and a successful update increments the pool's `version`. Rate changes never apply retroactively: `advance_amount` values already recorded on accepted deliveries stand at the rate that was in force at their acceptance.

Closing a pool — the `PoolManager` moving it `OPEN → CLOSED` — is allowed only when the pool's season has no delivery still in `RECEIVED`, `GRADED`, or `DISPUTED` status (`ERR_POOL_HAS_OPEN_DELIVERIES` otherwise), and, per §2.9, may push the season into `HARVEST_CLOSED` with its quota-locking cascade. A closed pool may be reopened for late adjustments while the season is `OPEN` or `HARVEST_CLOSED` — reopening under a `SETTLED` season is rejected with `ERR_SEASON_NOT_OPEN` — and reopening a pool of a `HARVEST_CLOSED` season reverts the season to `OPEN` and clears the quota locks.

Settlement converts a `CLOSED` pool into final money. The `PoolManager` settles by declaring the pool's `realized_revenue` and `operating_costs` alongside `expected_pool_version`. The preconditions, in their validation bands, are: the season must be `HARVEST_CLOSED` (`ERR_SEASON_NOT_OPEN` otherwise); the expected version must match (`ERR_STALE_VERSION`); and the money must be sane — `operating_costs` non-negative and `realized_revenue` at least `operating_costs`, and when the pool's `weighted_barrels_total` is zero both figures must be exactly zero — with violations rejected as `ERR_SETTLEMENT_INPUT_INVALID`. Settlement then evaluates in a pinned order: first the net pool value, `realized_revenue` minus `operating_costs` rounded half-up to two decimals; then the `final_rate_per_weighted_barrel`, the net pool value divided by `weighted_barrels_total` and rounded half-up to four decimals — or zero when the pool holds no weighted barrels, in which case no distributions are created at all. For each member with weighted barrels greater than zero in this pool, taken in member creation order (each member's `created_at`, ascending), a **PatronageDistribution** is created in `COMPUTED` status recording the member's `pool_id` and `member_id`, their `weighted_barrels` in the pool at settle, and three amounts: `gross_amount`, the member's weighted barrels times the final rate rounded half-up to two decimals; `retain_amount`, the gross times the pool's `retain_pct` rounded half-up to two decimals; and `advance_paid`, the sum of `advance_amount` over the member's `ACCEPTED`, non-`VOIDED` deliveries tagged to this pool. The `cash_amount` owed is the `gross_amount` minus the `retain_amount` minus the `advance_paid`, and it may legitimately be negative — an amount due back from the member. Whatever remains of the net pool value after the sum of all created distributions' gross amounts is the `coop_equity_residual`; it may be negative, it is retained by the co-op, and it is never reallocated to members. The pool lands in its terminal `SETTLED` status, and when every pool of the season has settled, the season itself advances to `SETTLED`. Distribution listings accept `pool_id`, `member_id`, and `status` filters.

Payment is deliberately bureaucratic: the `PoolManager` first approves a distribution (`COMPUTED → APPROVED`) and only then marks it paid (`APPROVED → PAID`), the terminal state. Any transition requested out of order — settling an `OPEN` pool, paying a `COMPUTED` distribution, reopening a `SETTLED` pool — is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — transitions, weigh-ins, grading, acceptance, settlement, and version-guarded updates — return `200 OK`. All endpoints are mounted under the `/coop` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coop/_clock/set_current_utc` | Advance the logical clock; runs the ticket expiry sweep | CoopAdmin |
| POST | `/coop/seasons` | Create a season (status SETUP) | CoopAdmin |
| GET | `/coop/seasons/{id}` | Get a season | Any authenticated role |
| POST | `/coop/seasons/{id}/open` | Open a season; creates MemberQuota rows for all ACTIVE members | CoopAdmin |
| POST | `/coop/members` | Register a member (status PENDING) | CoopAdmin |
| GET | `/coop/members/{id}` | Get a member | Any authenticated role |
| POST | `/coop/members/{id}/transition` | Member lifecycle transition (PENDING→ACTIVE, ACTIVE→SUSPENDED, SUSPENDED→ACTIVE, ACTIVE→WITHDRAWN) | CoopAdmin |
| GET | `/coop/quotas/{id}` | Get a member quota | Any authenticated role |
| GET | `/coop/quotas` | List quotas (filterable) | Any authenticated role |
| PATCH | `/coop/quotas/{id}` | Manually override base quota; OCC-guarded; blocked when locked | CoopAdmin |
| POST | `/coop/bogs` | Register a bog (status ACTIVE); GrowerMember caller becomes owner, CoopAdmin must pass member_id | GrowerMember, CoopAdmin |
| GET | `/coop/bogs/{id}` | Get a bog | Any authenticated role |
| GET | `/coop/bogs` | List bogs (filterable) | Any authenticated role |
| POST | `/coop/bogs/{id}/transition` | Renovation cycle transition (plan/cancel by owner or FieldOfficer; UNDER_RENOVATION, REPLANTED, certify by FieldOfficer) | GrowerMember, FieldOfficer |
| POST | `/coop/yield-estimates` | Submit a grower yield estimate for a bog+season (at most one per pair) | GrowerMember |
| GET | `/coop/yield-estimates/{id}` | Get a yield estimate | Any authenticated role |
| GET | `/coop/yield-estimates` | List yield estimates (filterable) | Any authenticated role |
| POST | `/coop/yield-estimates/{id}/transition` | Approve/flag (FieldOfficer) or revise a flagged estimate (owning GrowerMember) | GrowerMember, FieldOfficer |
| POST | `/coop/stations` | Register a receiving station | CoopAdmin |
| GET | `/coop/stations/{id}` | Get a receiving station | Any authenticated role |
| POST | `/coop/harvest-tickets` | Request a wet/dry harvest window on a bog (status REQUESTED) | GrowerMember |
| GET | `/coop/harvest-tickets/{id}` | Get a harvest ticket | Any authenticated role |
| GET | `/coop/harvest-tickets` | List harvest tickets (filterable) | Any authenticated role |
| POST | `/coop/harvest-tickets/{id}/transition` | Approve/complete (FieldOfficer) or cancel (owning GrowerMember or FieldOfficer) | GrowerMember, FieldOfficer |
| POST | `/coop/frost-events` | Declare a frost-protection sprinkler event on a bog | FieldOfficer |
| GET | `/coop/frost-events/{id}` | Get a frost event | Any authenticated role |
| GET | `/coop/frost-events` | List frost events (filterable) | Any authenticated role |
| POST | `/coop/frost-events/{id}/transition` | Activate/complete/cancel a frost event; completion evaluates vine damage | FieldOfficer |
| POST | `/coop/pools` | Create a marketing pool for a season (code MAIN or OVER_QUOTA; unique per season) | PoolManager |
| GET | `/coop/pools/{id}` | Get a pool | Any authenticated role |
| GET | `/coop/pools` | List pools (filterable) | Any authenticated role |
| PATCH | `/coop/pools/{id}` | Update provisional advance rate while OPEN; OCC-guarded; never retroactive | PoolManager |
| POST | `/coop/pools/{id}/transition` | Close (OPEN→CLOSED) or reopen (CLOSED→OPEN) a pool | PoolManager |
| POST | `/coop/pools/{id}/settle` | Settle a CLOSED pool: compute final rate, create distributions, mark SETTLED; OCC-guarded | PoolManager |
| POST | `/coop/deliveries` | Schedule a delivery appointment at a receiving station (status SCHEDULED) | GrowerMember |
| GET | `/coop/deliveries/{id}` | Get a delivery | Any authenticated role |
| GET | `/coop/deliveries` | List deliveries (filterable) | Any authenticated role |
| POST | `/coop/deliveries/{id}/receive` | Station confirms scale weights; computes net_barrels | StationOperator |
| POST | `/coop/deliveries/{id}/grade` | Record color/firmness/foreign-matter and compute grade; also re-grades from DISPUTED | StationOperator |
| POST | `/coop/deliveries/{id}/accept` | Accept a graded delivery into pool(s): quota split, pool tagging, advance booking | PoolManager |
| POST | `/coop/deliveries/{id}/dispute` | Grower disputes the grade (GRADED→DISPUTED) | GrowerMember |
| POST | `/coop/deliveries/{id}/void` | Void an accepted delivery; compensates quota, pool totals, and advances exactly | PoolManager |
| GET | `/coop/distributions/{id}` | Get a patronage distribution | Any authenticated role |
| GET | `/coop/distributions` | List patronage distributions (filterable) | Any authenticated role |
| POST | `/coop/distributions/{id}/transition` | Approve then pay a distribution (COMPUTED→APPROVED→PAID) | PoolManager |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_SEASON_YEAR` | 409 |
| `ERR_DUPLICATE_MEMBER_CODE` | 409 |
| `ERR_DUPLICATE_POOL_CODE` | 409 |
| `ERR_DUPLICATE_ESTIMATE` | 409 |
| `ERR_SEASON_NOT_OPEN` | 409 |
| `ERR_BOG_NOT_ACTIVE` | 409 |
| `ERR_TICKET_INVALID` | 409 |
| `ERR_QUOTA_LOCKED` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_WINDOW_OUTSIDE_SEASON` | 422 |
| `ERR_HARVEST_WINDOW_OVERLAP` | 409 |
| `ERR_STATION_CAPACITY_EXCEEDED` | 409 |
| `ERR_WATER_SCHEDULE_CONFLICT` | 409 |
| `ERR_TARE_EXCEEDS_GROSS` | 422 |
| `ERR_POOL_NOT_OPEN` | 409 |
| `ERR_OVER_QUOTA_POOL_UNAVAILABLE` | 409 |
| `ERR_POOL_HAS_OPEN_DELIVERIES` | 409 |
| `ERR_SETTLEMENT_INPUT_INVALID` | 422 |
