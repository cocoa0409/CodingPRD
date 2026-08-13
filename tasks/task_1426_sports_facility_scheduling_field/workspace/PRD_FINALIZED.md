# Sports Facility Scheduling API — Product Requirements Document

## 1. Introduction

Municipal athletics offices face the same puzzle every season: a finite inventory of diamonds, rectangles, and multipurpose fields must be divided fairly among youth leagues, adult leagues, schools, tournament operators, and corporate renters, all competing for the same desirable evening hours. Every decision has to be defensible — to council members, to losing applicants, and to auditors — which means allocation cannot live in spreadsheets and hallway conversations. The Sports Facility Scheduling API is the office's system of record for that entire puzzle: facility inventory and condition governance, fee schedule publication, seasonal application windows, deterministic priority scoring, weather-driven rescheduling, lights cost recovery, and the full fiscal lifecycle of every awarded hour.

Four operating roles share the workload. The athletics administrator sets policy, owns the inventory, runs the allocation, and approves money leaving the office; field supervisors own the physical truth of the turf — condition decisions, closures, check-ins, no-show marking, and settlement; organization coordinators file applications and manage their own permits; finance clerks issue invoices and move money. Underneath those workflows sit three guarantees the rest of this document develops in detail: scoring and capacity caps are deterministic and reproducible, every cent is accounted for through an explicit deposit-disposition waterfall, and chronic no-shows cascade into probation, suspension, and revocation without manual intervention.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request missing either header, or carrying an empty value for one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly four roles, spelled precisely as follows: `AthleticsAdmin`, `FieldSupervisor`, `OrgCoordinator`, and `FinanceClerk`. A caller whose role is not permitted to perform an operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the endpoint-by-endpoint role assignments appear in §4.

Role identity is bound to `X-User-ID` differently per role. When `X-User-Role` is `OrgCoordinator`, `X-User-ID` is the `id` of the acting Organization; ownership checks on any resource that references an Organization compare the resource's `organization_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_ORG_OWNERSHIP` (HTTP 403). When `X-User-Role` is `AthleticsAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `approved_by` on a refund the administrator approves — but never compares it to any entity's `id`. When `X-User-Role` is `FieldSupervisor`, `X-User-ID` is likewise an opaque operator identifier with no entity backing and no ownership comparison. When `X-User-Role` is `FinanceClerk`, `X-User-ID` is again opaque; the server records it as `initiated_by` on every payment or refund row the clerk creates, but performs no identity comparison against it.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

No temporal decision in this system ever reads wall-clock time. Window opening, slot-in-the-past rejection, cancellation notice tiers, no-show eligibility, the check-in window, and the reschedule horizon are all evaluated against a single server-side logical clock. Before any test-driving call, that clock reads exactly `2026-08-01T00:00:00Z`. An `AthleticsAdmin` may set the clock by supplying a `to_iso8601` instant to the clock capability listed in §4; the response reports the resulting `current_utc`. Every deadline comparison described in §3 reads this clock and nothing else.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. `version` is an integer that increments by one on every mutation and powers the optimistic concurrency checks of §2.7. The StrikeRecord is the sole exception to this contract: it is an immutable ledger entry carrying only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

### 2.6. Monetary Precision: Integer Cents and Line-by-Line Rounding

All monetary values in the system are integer counts of cents; no fractional cents exist anywhere. Every rounding performed by the pricing, penalty, and waterfall calculations is round half up to the nearest whole cent. Where a quote or invoice comprises several lines, each line is rounded independently first and the rounded lines are then summed — this evaluation order is pinned, and the alternative of summing unrounded raw values and rounding once at the end is a known-incorrect variant that yields different totals. Every fee exists in two variants: a provisional quote computed at award and recomputed at each reschedule, and a final settlement variant computed when a permit is completed; §3.6 gives both formulas in full.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field. Rescheduling a rained-out permit requires the request to carry `expected_permit_version`; recording a facility condition decision requires `expected_facility_version`; posting a manual invoice adjustment requires `expected_invoice_version`. In each case the field must equal the current `version` of the entity being acted upon — the permit, the facility, or the invoice respectively — as the client last observed it. When the supplied value does not match the entity's current `version`, because another write has advanced that version since the client's last read, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The stale request's only defect is its out-of-date view: the client may re-read the entity and retry with the fresh version, since successive reschedules, successive condition decisions, and successive adjustments are all legitimate under this specification.

### 2.8. Request Validation Order

Every request passes through a fixed validation pipeline, and the order is part of the contract: an earlier failure masks every later check, so the error a caller receives always comes from the earliest failing stage.

1. **Authentication context.** Both headers must be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). Applies to every endpoint.
2. **Request well-formedness.** The body must parse, all required input fields must be present, every enum value must be among its declared members, and every integer must lie inside its declared range — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint that accepts a body.
3. **Role authorization.** The caller's role must be permitted on the endpoint per §4, else `ERR_UNAUTHORIZED_ROLE` (403). Applies to every endpoint.
4. **Organization ownership.** When an `OrgCoordinator` acts on a specific application or permit — withdrawing an application, responding to an information request, or confirming, cancelling, or rescheduling a permit — `X-User-ID` must equal that resource's `organization_id`, else `ERR_FORBIDDEN_ORG_OWNERSHIP` (403). These five operations are the only ones carrying this check.
5. **Path existence.** Path identifiers are validated left to right, and the first missing resource produces its dedicated 404: `ERR_ORGANIZATION_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CLOSURE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, or `ERR_STRIKE_NOT_FOUND`.
6. **Segregation of duties.** The refund-approval operation alone carries this check: the approver's `X-User-ID` must differ from the refund row's `initiated_by`, else `ERR_SEGREGATION_OF_DUTIES` (403).
7. **State legality.** The target entity must be in a valid from-state for the requested transition: `ERR_INVALID_PERMIT_STATE`, `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_WINDOW_STATE`, `ERR_INVALID_INVOICE_STATE`, `ERR_INVALID_CLOSURE_STATE`, `ERR_INVALID_SCHEDULE_STATE`, `ERR_INVALID_PAYMENT_STATE`, or `ERR_INVALID_STRIKE_STATE` (all 409). Gates on an organization's standing surface as `ERR_ORG_SUSPENDED` (409).
8. **Facility safety gate.** New applications and reschedule targets are checked against facility condition and occupancy: a CLOSED facility yields `ERR_FACILITY_CLOSED`, and a `headcount` above the facility's `capacity` yields `ERR_HEADCOUNT_EXCEEDS_CAPACITY` (both 409).
9. **Temporal gates.** Submitting into a window that is not OPEN yields `ERR_WINDOW_NOT_OPEN`; opening a window before its `opens_at` yields `ERR_WINDOW_NOT_YET_OPEN`; a slot starting at or before the logical clock yields `ERR_SLOT_IN_PAST`; a reschedule date outside its horizon yields `ERR_RESCHEDULE_HORIZON_EXCEEDED`; marking a no-show before the slot has ended yields `ERR_NO_SHOW_NOT_YET`; and checking in outside the check-in window yields `ERR_CHECKIN_WINDOW_CLOSED` (all 409).
10. **Constraint gates.** The allocation run, rescheduling, application slot durations, and closure intervals are guarded by `ERR_SLOT_OVERLAP`, `ERR_LIGHTS_BUFFER_OVERLAP`, `ERR_PRIME_CAP_EXCEEDED`, `ERR_TURF_REST_CAP_EXCEEDED`, `ERR_RESCHEDULE_LIMIT_REACHED`, and `ERR_INVALID_TIME_RANGE` (all 409).
11. **Fiscal gates.** Confirmation, payments, refunds, voiding, and adjustments are guarded by `ERR_DEPOSIT_NOT_PAID`, `ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_REFUND_EXCEEDS_PAID`, and `ERR_INVOICE_HAS_PAYMENTS` (all 422).

### 2.9. Slots, Prime Time, Turf Rest, and the Lights Grid

Three capacity regimes recur throughout the allocation and rescheduling workflows, and they share vocabulary defined here.

**Half-open slots.** Every slot is a half-open interval: a permit occupies the minutes from `start_minute` up to but not including `end_minute`. Two slots on the same facility and date overlap only when their intervals share at least one minute; adjacency — one slot's `end_minute` equal to the other's `start_minute` — is not overlap, and back-to-back bookings coexist peacefully.

**Prime time.** A slot is prime when its `start_minute` is at least 1020 — 5:00 PM local time, 1020 minutes after midnight. A slot's prime hours are its duration expressed in hours when the slot is prime, and zero otherwise; all cap accounting is done in whole hours.

**Turf rest.** To protect playing surfaces, each facility declares `weekly_prime_hour_cap`, the maximum prime hours that may be held by permits in `RESERVED` or `CONFIRMED` status within a single calendar week, where a week runs Monday through Sunday. The check is always evaluated against the week containing the candidate slot: the candidate may be placed only when that week's existing prime load plus the candidate's own prime hours is less than or equal to the cap — the boundary is inclusive, so landing exactly on the cap is allowed. Separately, the facility's display counter `weekly_prime_hours_used` always reflects the prime load of the week containing the logical clock's date, and it is recomputed on every permit mutation; because setting the logical clock can move that week, every facility's counter is also recomputed within the same request whenever the clock is set.

**The lights grid.** Light approval is governed by a 30-minute buffer and a nightly budget. A permit's lights window is its slot interval when lights are approved. Two lights windows on the same facility and date conflict when the gap between them is strictly less than 30 minutes — measured from the earlier window's end to the later window's start, symmetrically in either order — while a gap of exactly 30 minutes is permitted. A facility's `nightly_light_block_cap` bounds the total number of 15-minute light blocks approvable per calendar date, where each permit contributes its approved lights minutes divided by 15 and rounded up to a whole block; the cap is inclusive, so a date landing exactly on the cap is allowed.

### 2.10. Derived Counters and Cross-Entity Reconciliation

Several counters exist only as derived reconciliations over other entities, and the server keeps them exact at all times within the same request as the triggering event; none of them accepts a direct write. An organization's `no_show_strikes_active` is the count of its StrikeRecord rows in `ACTIVE` status, recomputed whenever a strike is created or rescinded. A UsageLedger accumulates per organization and season: `awarded_prime_hours` and `awarded_nonprime_hours` count the hours held by that organization's permits in `RESERVED` or `CONFIRMED` status and rise on award and fall on release; `attended_hours` grows at settlement; `no_show_count` grows when a permit is marked as a no-show. A facility's `weekly_prime_hours_used` recomputes on every permit mutation, as §2.9 describes. An invoice's `paid_cents`, `refunded_cents`, and `balance_due_cents` recompute whenever a payment or refund clears. Cascades are deterministic: when a parent decision forces child changes — a suspension revoking permits, a closure raining out slots — every affected entity is reconciled in the same request, with each mutated entity's `version` incremented and `updated_at` refreshed.

## 3. Business Logic & Workflows

### 3.1. Registering Organizations and the Strike Economy

An `AthleticsAdmin` registers each participating organization with a legal `name`, a `classification` of `RESIDENT`, `NONRESIDENT`, or `COMMERCIAL`, and an `org_type` of `YOUTH_LEAGUE`, `ADULT_LEAGUE`, `SCHOOL`, `TOURNAMENT_OPERATOR`, or `CORPORATE`. The `prior_seasons_active` field records how many earlier seasons included any awarded usage for the organization; it defaults to 0 and may never be negative. New organizations begin with `standing` `GOOD` and `no_show_strikes_active` at 0.

Strikes are the discipline currency of the league. When a field supervisor marks a confirmed permit as a no-show (§3.6), the system creates a StrikeRecord linking the `organization_id` to the offending `permit_id` and stores `strike_points` equal to ten times the organization's new active-strike count including the strike just created — a first strike records 10 points, a second records 20, a third records 30. StrikeRecords are immutable once created and begin in `ACTIVE` status; each one eventually either stays `ACTIVE` or is rescinded into the terminal `RESCINDED` status.

Standing re-evaluates on every change to the active strike count. The moment the count becomes exactly 2, the organization falls from `GOOD` to `PROBATION`. The moment the count reaches 3 or more, the organization becomes `SUSPENDED` — including a direct `GOOD` → `SUSPENDED` fall when a single event pushes the count from below 2 to 3 or more in one step, and the ordinary `PROBATION` → `SUSPENDED` fall otherwise. Suspension triggers the revocation cascade: every permit the organization holds in `RESERVED` or `CONFIRMED` status whose `permit_date` falls on or after the current logical date transitions to `REVOKED` under the fault code `ORG_FAULT`; each revoked permit's invoice runs the deposit waterfall of §3.8 with `penalty_cents` set to the full `deposit_cents` — the deposit is forfeited — while any remaining `balance_due_cents` stays owed; the released hours come out of the season's UsageLedger, with `awarded_prime_hours` and `awarded_nonprime_hours` decremented accordingly; each affected facility's `weekly_prime_hours_used` is recomputed; and every `WAITLISTED` application belonging to the organization is denied with `decision_note` `ORG_SUSPENDED`.

Rescission and reinstatement provide the way back. An administrator may rescind an `ACTIVE` strike; attempting to rescind one already `RESCINDED` is rejected with `ERR_INVALID_STRIKE_STATE`. Rescission recomputes `no_show_strikes_active` and re-evaluates standing immediately: a `PROBATION` organization whose active count has fallen below 2 returns to `GOOD` automatically, while a `SUSPENDED` organization stays `SUSPENDED` no matter how far the count falls — only an explicit administrative reinstatement lifts a suspension, moving the organization `SUSPENDED` → `PROBATION`. Reinstatement itself re-evaluates standing within the same request, so when the active count is already below 2 the follow-on `PROBATION` → `GOOD` transition fires immediately as part of that request. Every standing change increments the organization's `version` and refreshes its `updated_at`.

Strike history can be browsed through the strike listing with filters on `organization_id`, `permit_id`, and `status`, ordered by creation ascending so indexed reads are stable. Season-by-season participation is visible through the usage-ledger listing with filters on `organization_id` and `season_code`.

### 3.2. Facility Inventory and Condition Governance

Administrators register each facility with a `name`; a `facility_class` of `DIAMOND`, `RECTANGLE`, or `MULTIPURPOSE`; a `has_lights` flag indicating whether a lights grid exists; a `capacity` of at least 1, which is the occupancy safety limit enforced at application time; a `weekly_prime_hour_cap` of at least 1 per §2.9; and a `nightly_light_block_cap` of at least 1 bounding the cost-recovery budget for lights per date. A new facility begins with `condition_status` `OPEN`, an empty `condition_reason`, and `weekly_prime_hours_used` at 0.

Only a `FieldSupervisor` records condition decisions. A decision sets `condition_status` to `OPEN`, `LIMITED`, or `CLOSED` — every pairwise transition among the three states is legal, in either direction — copies the decision's `reason` text into `condition_reason`, and increments the facility's `version`. The operation is OCC-guarded per §2.7: the request must carry `expected_facility_version` matching the facility's current `version`, else it fails with `ERR_STALE_VERSION`. Recording a decision against a facility that does not exist yields `ERR_FACILITY_NOT_FOUND`.

While a facility is `CLOSED`, two operations are blocked: new permit applications naming that facility are rejected with `ERR_FACILITY_CLOSED`, and rain reschedules targeting it fail the same way (§3.7). The intermediate `LIMITED` state is advisory — it records degraded conditions for coordinators to see without blocking any scheduling.

### 3.3. Fee Schedules and Rate Publishing

Seasonal pricing lives on fee schedules, created in `DRAFT` status by an administrator. A schedule carries a `name`, an `effective_from` date marking when it may first be pinned to new awards, and twelve numeric policy fields: the three hourly rates `hourly_resident_cents`, `hourly_nonresident_cents`, and `hourly_commercial_cents`; the `lights_block_cents` price per 15-minute lights block; the `nonresident_surcharge_pct` and `commercial_surcharge_pct`, each between 0 and 100 inclusive and applied to the rounded field-fee line; the `tournament_day_cents` flat day rate together with its qualifying threshold `tournament_day_min_minutes` of at least 60; and the deposit policy, `deposit_pct` between 1 and 100 with a `min_deposit_cents` floor. Rates, prices, and the deposit floor may never be negative; values outside their declared ranges fail at intake with `ERR_INVALID_REQUEST`.

Publishing is the transition `DRAFT` → `PUBLISHED`, performed by an administrator, and it requires that `effective_from` lie no more than 365 days beyond the logical clock's current date. Publishing a schedule that is not in `DRAFT` is rejected with `ERR_INVALID_SCHEDULE_STATE`. At most one schedule is `PUBLISHED` at any moment: publishing a new schedule automatically moves the previously `PUBLISHED` one to `SUPERSEDED`, a terminal state, and each side of that handoff increments its own schedule's `version`. Awards pin whichever schedule is `PUBLISHED` at decision time onto the new permit's `fee_schedule_id`, so later republication never reprices permits that already exist.

### 3.4. The Allocation Season: Windows and Applications

Each season is administered as an allocation window carrying a `season_code` label such as 2026-FALL, an `opens_at` instant before which the window may not open, a `closes_at` instant strictly later than `opens_at`, a `prime_cap_hours_per_org` of at least 1 bounding each organization's awarded prime hours for the season, and a `max_tournament_days_per_org` of 0 or more bounding each organization's tournament days for the season. Both caps are inclusive boundaries. A new window begins `SCHEDULED`.

An administrator opens a `SCHEDULED` window only once the logical clock has reached `opens_at`; opening earlier fails with `ERR_WINDOW_NOT_YET_OPEN`, and opening, closing, or running allocation on a window in the wrong state fails with `ERR_INVALID_WINDOW_STATE`. Closing an `OPEN` window sweeps every application still `SUBMITTED` under that window into `UNDER_REVIEW` within the same request, each application's `version` incrementing as it moves.

While a window is `OPEN` — submissions at any other time fail with `ERR_WINDOW_NOT_OPEN` — an `OrgCoordinator` files an application naming the `window_id`, the requested `facility_id`, the `event_date` as a YYYY-MM-DD calendar date, `start_minute` and `end_minute` as minutes from midnight forming the half-open slot of §2.9, an `event_type` of `LEAGUE_GAME`, `LEAGUE_PRACTICE`, `TOURNAMENT`, or `SPECIAL_EVENT`, an optional `wants_lights` flag that defaults to false, and a `headcount` of at least 1. The `start_minute` must lie between 0 and 1439, the `end_minute` must be strictly later than `start_minute` and no greater than 1440, and the slot must last at least 30 minutes and at most 480 minutes; violations are rejected with `ERR_INVALID_TIME_RANGE`. A requested slot starting at or before the logical clock is rejected with `ERR_SLOT_IN_PAST`, a `headcount` above the facility's `capacity` with `ERR_HEADCOUNT_EXCEEDS_CAPACITY`, and a `CLOSED` facility with `ERR_FACILITY_CLOSED`. The server stamps the application with the caller's organization as its `organization_id`, computes the provisional priority score of §3.5 and stores it on `provisional_score`, and sets `status` to `SUBMITTED` with `final_score` still null and `decision_note` empty.

Once the window has closed, review is conversational. An administrator reviewing an `UNDER_REVIEW` application may push it to `NEEDS_INFO` with a `note`, which is recorded as the application's `decision_note`; this is only possible while the parent window is `CLOSED`. The owning coordinator then answers with a `response_note`, returning the application `NEEDS_INFO` → `UNDER_REVIEW`, and the loop may repeat without limit. Acting on an application that is not in the expected from-state — requesting information from a `SUBMITTED` application, say — fails with `ERR_INVALID_APPLICATION_STATE`, and a coordinator acting on another organization's application fails with `ERR_FORBIDDEN_ORG_OWNERSHIP`.

The owning coordinator may also withdraw an application from `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_INFO`, or `WAITLISTED`, landing it in the terminal `WITHDRAWN` state. Applications can be browsed through the listing with filters on `window_id`, `organization_id`, `facility_id`, and `status`.

### 3.5. Priority Scoring, the Allocation Run, and Waitlist Promotion

Every application carries two scores produced by the same priority formula. The provisional variant is snapshotted at submission time using the organization's counters as they stand at that instant; the final variant is recomputed during the allocation run with organization counters frozen at run time, so a strike landing between submission and the run changes `final_score` but never `provisional_score`. The formula sums six components and floors the result at zero:

- Base points come from classification: 80 for `RESIDENT`, 45 for `NONRESIDENT`, 25 for `COMMERCIAL`.
- An organization-type modifier adds 15 for `YOUTH_LEAGUE`, 12 for `SCHOOL`, 6 for `ADULT_LEAGUE`, nothing for `CORPORATE`, and subtracts 5 for `TOURNAMENT_OPERATOR`.
- Loyalty adds 3 points per prior active season from `prior_seasons_active`, capped at 12 points total.
- A utilization bonus looks backward across seasons: ignoring the season now being allocated, take the organization's UsageLedger rows from prior seasons ordered by `season_code` descending and select the most recent row that has any awarded history. Its utilization is the ratio of `attended_hours` to the sum of `awarded_prime_hours`, `awarded_nonprime_hours`, and `attended_hours`, compared as an exact rational — attended hours multiplied by 100 is compared against 80 (respectively 60) multiplied by that total, with no rounding of the ratio itself. Utilization of at least 80 percent earns 10 points; at least 60 percent earns 5; anything lower — including the case where no qualifying prior ledger exists and utilization is null — earns 0.
- Each active no-show strike subtracts 12 points, using `no_show_strikes_active`.
- The event-type modifier adds 8 for `LEAGUE_GAME`, 4 for `LEAGUE_PRACTICE`, nothing for `SPECIAL_EVENT`, and subtracts 10 for `TOURNAMENT`.

Running allocation on a `CLOSED` window — which requires a `PUBLISHED` fee schedule to exist, failing with `ERR_INVALID_SCHEDULE_STATE` otherwise — walks every application of the window that is in `UNDER_REVIEW` in a deterministic order: `final_score` descending, with ties broken by earlier `created_at`. Each application is then decided against a sequence of gates, evaluated in this order. An application whose organization is `SUSPENDED` at run time is denied outright, landing in `DENIED` with `decision_note` `ORG_SUSPENDED`. An application whose half-open slot overlaps any application already awarded in this run, or any existing `RESERVED` or `CONFIRMED` permit on the same facility and date, is waitlisted as `WAITLISTED` with `decision_note` `SLOT_CONFLICT`. One whose award would push the organization's season `awarded_prime_hours` plus the new slot's prime hours above the window's `prime_cap_hours_per_org` is waitlisted with `PRIME_CAP` — landing exactly at the cap is allowed. One that would push the facility's weekly prime load for the slot's week above `weekly_prime_hour_cap` is waitlisted with `TURF_REST_CAP`, again with an inclusive boundary. And a `TOURNAMENT` application whose award would raise the organization's tournament day count for the season above `max_tournament_days_per_org` is waitlisted with `TOURNAMENT_CAP`.

An application passing every gate is awarded, and the award fans out into several records at once. The system creates a Permit in `RESERVED` status with `fee_schedule_id` pinned to the currently `PUBLISHED` schedule, computes the provisional fee quote of §3.6 onto the permit, and decides lights per the grid rules of §2.9 — a buffer conflict or a breached nightly cap never blocks the award itself; the permit is simply awarded with `lights_approved` false and `lights_minutes_quoted` 0. The permit's Invoice is created in `DRAFT` status with the provisional quote lines and a snapshot of the deposit. The organization's UsageLedger for the window's `season_code` is created on first award, and `awarded_prime_hours` and `awarded_nonprime_hours` rise by the slot's prime and non-prime hours. Each affected facility's `weekly_prime_hours_used` is recomputed, every created or mutated entity's `version` increments, and the run leaves the window `ALLOCATED`, a terminal state.

Waitlisted applications get a second chance whenever a cancellation or revocation frees a slot. The promotion pool is the `WAITLISTED` applications of the same window naming the same `facility_id` and `event_date`, ranked by `final_score` descending and then `created_at` ascending; the first candidate whose slot fits the freed interval, with all caps re-checked and passing, is promoted to `AWARDED` with the full award fan-out described above. An empty pool, or a pool where no candidate fits, makes the promotion a no-op.

### 3.6. Permit Life: Confirmation, Check-In, Settlement, and No-Shows

A Permit is born only from an award — the allocation run or a waitlist promotion — and never created directly by any client. It carries its originating `application_id`, the `organization_id` and `facility_id` taken from that application, the `fee_schedule_id` pinned at award, and the slot as `permit_date`, `start_minute`, and `end_minute`, with `event_type` copied from the application. Its lights disposition is recorded as `lights_approved` and `lights_minutes_quoted`; its provisional quote lives on `quoted_field_fee_cents`, `quoted_lights_fee_cents`, `quoted_surcharge_cents`, and `quoted_total_cents`, with `deposit_required_cents` alongside. The `final_total_cents` stays null until settlement, `attendance_minutes` stays null until check-in, `rain_reschedule_count` starts at 0, and `original_permit_id` starts null. A permit's `status` begins at `RESERVED` and ends at one of four terminal states: `COMPLETED`, `CANCELLED`, `NO_SHOW`, or `REVOKED`. Permits can be browsed through the listing with filters on `organization_id`, `facility_id`, `application_id`, `fee_schedule_id`, `original_permit_id`, `permit_date`, and `status`.

The provisional quote at award — and again at every reschedule — follows a pinned recipe. The slot's duration in minutes is `end_minute` minus `start_minute`. When the event is a `TOURNAMENT` and the duration reaches at least the pinned schedule's `tournament_day_min_minutes`, the raw field fee is the flat `tournament_day_cents` day rate, which replaces hourly billing entirely. Otherwise the applicable hourly rate — `hourly_resident_cents`, `hourly_nonresident_cents`, or `hourly_commercial_cents`, selected by the organization's `classification` — is multiplied by the duration and divided by 60 using exact rational arithmetic. The field line `quoted_field_fee_cents` is that raw amount rounded half-up to whole cents. The lights line prices `lights_minutes_quoted` — which equals the slot's full duration when lights were approved and 0 otherwise — by dividing it into 15-minute blocks rounded up to a whole block and multiplying by the pinned `lights_block_cents`, yielding `quoted_lights_fee_cents`. The surcharge line applies only to `NONRESIDENT` and `COMMERCIAL` organizations: it is the already-rounded field line multiplied by `nonresident_surcharge_pct` or `commercial_surcharge_pct` respectively, divided by 100, and rounded half-up; `RESIDENT` organizations pay no surcharge. Per §2.6, each line is rounded independently and the rounded lines are then summed into `quoted_total_cents`. The `deposit_required_cents` is the smaller of the quoted total and the larger of two floors: `min_deposit_cents`, and the quoted total multiplied by `deposit_pct` divided by 100 and rounded half-up.

Confirmation turns a `RESERVED` permit `CONFIRMED`, and only the owning coordinator may do it — acting on another organization's permit fails with `ERR_FORBIDDEN_ORG_OWNERSHIP`, and attempting the transition from any other status fails with `ERR_INVALID_PERMIT_STATE`. Three gates must pass: the organization's `standing` must not be `SUSPENDED`, else `ERR_ORG_SUSPENDED`; the permit's invoice must be `ISSUED`, `PARTIALLY_PAID`, or `PAID`, else `ERR_INVALID_INVOICE_STATE`; and cleared payments must cover the deposit — the invoice's `paid_cents` at least its `deposit_cents` — else `ERR_DEPOSIT_NOT_PAID`. A successful confirmation simply advances the permit and increments its `version`.

On game day, the field supervisor records attendance against a `CONFIRMED` permit by submitting `attended_minutes`, which must be at least 15 and no more than the slot's full duration, and which lands in the permit's `attendance_minutes`. Check-in is accepted only within a window that opens 30 minutes before the slot start and closes at the slot end; outside that window the rejection is `ERR_CHECKIN_WINDOW_CLOSED`.

Settlement is the permit's happy ending: after the slot has ended, the supervisor settles a checked-in `CONFIRMED` permit into `COMPLETED`. Attempting settlement without a check-in fails with `ERR_CHECKIN_REQUIRED`, and the logical clock must be past the slot's end. Settlement recomputes the quote in its final variant. The final field fee is the smaller of the quoted field fee and the pinned hourly rate multiplied by `attendance_minutes`, divided by 60, and rounded half-up. The final lights fee is the smaller of the quoted lights fee and the actual usage priced per block — the optional `actual_lights_minutes` divided by 15, rounded up to whole blocks, at the pinned `lights_block_cents`; when lights were never approved, the quoted lights line is zero, so the final lights line is zero as well. The surcharge line carries over from the provisional quote unchanged, so the final total can diverge downward from the provisional one but never upward through this mechanism. The permit's `final_total_cents` records the recomputed total; the invoice's lines are updated and its `total_cents` and `balance_due_cents` recomputed; the season ledger releases the slot's awarded hours and adds `attendance_minutes` divided by 60 — integer division, per permit — to `attended_hours`; and the facility's `weekly_prime_hours_used` is recomputed.

When a `CONFIRMED` slot ends with no check-in recorded, the field supervisor marks a no-show. Doing so before the slot end has passed fails with `ERR_NO_SHOW_NOT_YET`, and a permit already carrying `attendance_minutes` cannot be marked at all. Marking fans out widely: the StrikeRecord of §3.1 is created and the organization's standing is re-evaluated with the full cascade; the invoice's `penalty_cents` is set to the full `deposit_cents` and the deposit waterfall of §3.8 runs, with any remaining total still owed; the season ledger releases the awarded hours and increments `no_show_count`; and the facility's `weekly_prime_hours_used` is recomputed. The permit ends in the terminal `NO_SHOW` state.

### 3.7. Weather Disruption: Closures, Rain-Outs, and Rescheduling

Field supervisors declare closures with a `facility_id`, a `closure_date`, an optional `start_minute` and `end_minute` pair — omitting both declares a full-day closure, while providing them requires a valid half-open interval with `end_minute` strictly after `start_minute`, else `ERR_INVALID_TIME_RANGE` — and a `reason` of `RAIN`, `TURF_REST`, `MAINTENANCE`, or `SAFETY`. A new closure begins `ACTIVE`.

Creating an `ACTIVE` closure immediately rains out every permit on that facility and date in `RESERVED` or `CONFIRMED` status whose slot intersects the closure — any slot at all for a full-day closure, otherwise half-open interval overlap per §2.9. Each affected permit moves to `RAINED_OUT`. Its invoice is credited with `credit_cents` equal to the sum of `field_fee_cents`, `lights_fee_cents`, and `surcharge_cents`; `total_cents` recomputes to whatever `adjustment_cents` remains, typically zero; and `balance_due_cents` recomputes and may legitimately go negative, representing a credit on account — no money moves automatically, and funds return only through the cancellation waterfall. The released hours leave the season ledger, and the facility's `weekly_prime_hours_used` is recomputed. Closures can be browsed through the listing with filters on `facility_id`, `closure_date`, and `status`.

Lifting an `ACTIVE` closure moves it to the terminal `LIFTED` state; lifting a closure already lifted fails with `ERR_INVALID_CLOSURE_STATE`. Lifting never reverts rained-out permits — the cascade is deliberately one-way and deterministic, and affected organizations must use the reschedule path instead.

Rescheduling returns a `RAINED_OUT` permit to `CONFIRMED` on a new slot. The owning coordinator or an administrator supplies `new_date`, `new_start_minute`, `new_end_minute`, and the OCC field `expected_permit_version` per §2.7. Eight guards protect the move, each with its own rejection: the version check fails with `ERR_STALE_VERSION`; a `rain_reschedule_count` already at its hard cap of 2 fails with `ERR_RESCHEDULE_LIMIT_REACHED`; a `CLOSED` target facility fails with `ERR_FACILITY_CLOSED`; a `new_date` before the permit's current `permit_date` or more than ten days after it fails with `ERR_RESCHEDULE_HORIZON_EXCEEDED`; a new slot starting at or before the logical clock fails with `ERR_SLOT_IN_PAST`; a half-open overlap with another `RESERVED` or `CONFIRMED` permit on the same facility and date fails with `ERR_SLOT_OVERLAP`; when lights were approved on the permit, a breach of the 30-minute buffer or the nightly block cap of §2.9 fails with `ERR_LIGHTS_BUFFER_OVERLAP`; and a breach of the season prime cap or the weekly turf cap fails with `ERR_PRIME_CAP_EXCEEDED` or `ERR_TURF_REST_CAP_EXCEEDED` respectively.

A successful reschedule replaces `permit_date`, `start_minute`, and `end_minute` with the new slot; sets `original_permit_id` to the lineage root — on the first reschedule the null becomes the permit's own `id`, the root of its reschedule lineage, and any later reschedule keeps that same root; and increments both `rain_reschedule_count` and `version`. The fees are re-quoted: the new provisional lines replace the invoice's field, lights, and surcharge lines; `credit_cents` and `adjustment_cents` reset to 0 because the rain credit is consumed by the replacement slot; and `total_cents` and `balance_due_cents` recompute, so the organization's earlier payments absorb into the new charges. The season ledger re-adds the awarded hours for the new slot and the facility's weekly counter recomputes. One hazard survives the move: if an `ACTIVE` closure already intersects the brand-new slot — same facility, `closure_date` equal to the new date, overlapping interval — the rain-out cascade fires again within the same request, and the permit lands back in `RAINED_OUT` with its `version` advanced a second time.

A rained-out permit may instead be cancelled outright, by the owning coordinator or an administrator. Weather is never the organization's fault, so the rain cancellation assesses `penalty_cents` of 0, and the deposit waterfall refunds the entire net-paid amount — creating a `REFUND` payment, which goes to `PENDING_APPROVAL` when it exceeds 10,000 cents per §3.8. The invoice total stays 0, and once cleared refunds equal `paid_cents` with the total at 0 the invoice moves to `REFUNDED` on its own.

### 3.8. Money Movement: Invoices, Payments, Cancellations, and the Deposit Waterfall

Exactly one invoice exists per permit, created in `DRAFT` status at award and carrying the `permit_id` and `organization_id`. Its lines mirror the permit's provisional quote — `field_fee_cents`, `lights_fee_cents`, and `surcharge_cents` — alongside `credit_cents`, `adjustment_cents`, and `penalty_cents`, each starting at 0. The `total_cents` is the amount owed: field plus lights plus surcharge plus adjustments minus credit — or, after a cancel-style closeout, simply the penalty. The `deposit_cents` snapshots the permit's `deposit_required_cents` at invoice creation; `paid_cents` sums the cleared `PAYMENT` rows and `refunded_cents` the cleared `REFUND` rows; and `balance_due_cents` is the total minus net payments, where net means paid minus refunded. The three waterfall buckets `deposit_penalty_applied_cents`, `deposit_balance_applied_cents`, and `deposit_refunded_cents` all start at 0. Invoices can be browsed through the listing with filters on `organization_id`, `permit_id`, and `status`.

A `FinanceClerk` issues a `DRAFT` invoice, moving it to `ISSUED`, or voids one outright. Voiding requires zero cleared payments: a `DRAFT` or `ISSUED` invoice with `paid_cents` at 0 becomes `VOID`, while any invoice holding payments fails with `ERR_INVOICE_HAS_PAYMENTS` — which means the `PARTIALLY_PAID` → `VOID` path always fails fiscally, existing only to keep that error reachable. Issuing or voiding from a wrong state fails with `ERR_INVALID_INVOICE_STATE`.

Recording a payment takes an `amount_cents` of at least 1 and a `method` of `CHECK`, `CARD`, `CASH`, or `CREDIT`, and creates a Payment row of `kind` `PAYMENT` directly in `CLEARED` status. The amount may not exceed the invoice's `balance_due_cents`, else `ERR_PAYMENT_EXCEEDS_BALANCE`. Cleared payments recompute `paid_cents` and `balance_due_cents` and advance the invoice on their own: `ISSUED` → `PARTIALLY_PAID` while a balance remains, and on to `PAID` once the balance reaches 0. Payments can be browsed through the listing with filters on `invoice_id`, `organization_id`, `kind`, and `status`.

Refunds are the mirror flow. A clerk initiates one with an `amount_cents` and a `reason`, capped at the net paid amount — `paid_cents` minus `refunded_cents` — else `ERR_REFUND_EXCEEDS_PAID`. A refund of 10,000 cents or less is created directly in `CLEARED` status; a larger one starts `PENDING_APPROVAL` and moves money only after an administrator approves it. Approval requires the payment to still be `PENDING_APPROVAL`, else `ERR_INVALID_PAYMENT_STATE`, and segregation of duties applies: an approver whose `X-User-ID` equals the row's `initiated_by` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval stamps `approved_by`, adds the amount to the invoice's `refunded_cents`, recomputes `balance_due_cents`, and — when cleared refunds fully cover the net paid amount with the invoice total at 0 — settles the invoice to `REFUNDED` from either `PAID` or `PARTIALLY_PAID`. Every Payment row remembers its creator as `initiated_by` and, once approved, its approver as `approved_by`.

Clerks may also post a signed manual `delta_cents` with an explanatory `note` against an invoice in `ISSUED` or `PARTIALLY_PAID` status; any other invoice state fails with `ERR_INVALID_INVOICE_STATE`. The operation is OCC-guarded per §2.7 through `expected_invoice_version`. The delta accumulates into `adjustment_cents`, and `total_cents` and `balance_due_cents` recompute.

Cancelling a permit — by its owning coordinator or by an administrator — closes it out fiscally, and the notice period drives the penalty. From `RESERVED`, cancellation is free: the penalty tier is 0 percent. From `CONFIRMED`, cancellation must precede the slot start — cancelling at or after the start fails with `ERR_INVALID_PERMIT_STATE` — and the notice period, measured as the whole hours between the logical clock and the slot start with fractional hours discarded, sets the tier: at least 168 hours (seven days) of notice costs nothing; at least 48 hours costs 15 percent; at least 24 hours costs 30 percent; anything shorter costs 50 percent. The penalty is the permit's pre-cancel `quoted_total_cents` multiplied by the tier percent, divided by 100, and rounded half-up. The evaluation order is pinned: the penalty is computed against the pre-cancel quoted total; then the invoice's `total_cents` is replaced by `penalty_cents`; and only then does the deposit waterfall run — never the reverse. In every cancellation the awarded hours leave the season ledger, the facility's `weekly_prime_hours_used` recomputes, waitlist promotion per §3.5 runs for the freed slot, and the permit lands in the terminal `CANCELLED` state.

The deposit-disposition waterfall decides what happens to the deposit at every closeout — cancellation, no-show, revocation under either fault code, and rain-out settlement. First, the deposit held is the smaller of the net payments (`paid_cents` minus `refunded_cents`) and the invoice's `deposit_cents`. That held amount then drains through three buckets in order. Bucket one, `deposit_penalty_applied_cents`, absorbs as much of the held deposit as the invoice's `penalty_cents` allows. Bucket two, `deposit_balance_applied_cents`, absorbs from what remains an amount up to the non-penalty balance still owed — the larger of zero and `total_cents` minus `penalty_cents`. Bucket three, `deposit_refunded_cents`, receives whatever is left. Money is conserved: at every closeout the three buckets sum exactly to the deposit held. A positive refund bucket creates a `REFUND` Payment of exactly that amount, subject to the 10,000-cent approval threshold described above.

Revocation is the administrative hammer. An `AthleticsAdmin` revokes a `RESERVED` or `CONFIRMED` permit by supplying a `fault` of `ORG_FAULT` or `ADMIN_DISCRETION` — revoking from any other status fails with `ERR_INVALID_PERMIT_STATE` — and the suspension cascade of §3.1 revokes with `ORG_FAULT` automatically. Under `ORG_FAULT` the penalty equals the full `deposit_cents`, forfeiting the deposit; under `ADMIN_DISCRETION` the penalty is 0 and all paid amounts come back through the waterfall's refund bucket. Either way the waterfall runs, a `REFUND` payment is created whenever the refundable remainder is positive, the season ledger releases the awarded hours, the facility's weekly counter recomputes, waitlist promotion runs for the freed slot, and the permit ends in the terminal `REVOKED` state.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an organization, facility, fee schedule, allocation window, permit application, field closure, or a payment/refund record — return `201 Created`. All other successful operations, including reads, state transitions, and adjustments to existing resources, return `200 OK`. In the table below, "Any authenticated role" means all four roles of §2.1 (`AthleticsAdmin`, `FieldSupervisor`, `OrgCoordinator`, `FinanceClerk`); request and response payloads for each operation are as narrated in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the test-driving logical clock | AthleticsAdmin |
| POST | `/organizations` | Register an organization | AthleticsAdmin |
| GET | `/organizations/{id}` | Get an organization | Any authenticated role |
| POST | `/organizations/{id}/reinstate` | Reinstate a SUSPENDED organization to PROBATION | AthleticsAdmin |
| POST | `/facilities` | Register a facility | AthleticsAdmin |
| GET | `/facilities/{id}` | Get a facility | Any authenticated role |
| POST | `/facilities/{id}/condition` | Record a condition decision (OCC-guarded) | FieldSupervisor |
| POST | `/fee-schedules` | Create a fee schedule in DRAFT | AthleticsAdmin |
| GET | `/fee-schedules/{id}` | Get a fee schedule | Any authenticated role |
| POST | `/fee-schedules/{id}/publish` | Publish a DRAFT schedule, superseding the current one | AthleticsAdmin |
| POST | `/allocation-windows` | Create an allocation window in SCHEDULED | AthleticsAdmin |
| GET | `/allocation-windows/{id}` | Get an allocation window | Any authenticated role |
| POST | `/allocation-windows/{id}/open` | Open a SCHEDULED window | AthleticsAdmin |
| POST | `/allocation-windows/{id}/close` | Close an OPEN window, sweeping applications to review | AthleticsAdmin |
| POST | `/allocation-windows/{id}/run-allocation` | Score and decide all applications under review | AthleticsAdmin |
| POST | `/permit-applications` | Submit an application into an OPEN window | OrgCoordinator |
| GET | `/permit-applications` | List applications with filters | Any authenticated role |
| GET | `/permit-applications/{id}` | Get an application | Any authenticated role |
| POST | `/permit-applications/{id}/withdraw` | Withdraw an application | OrgCoordinator |
| POST | `/permit-applications/{id}/request-info` | Request more information from the applicant | AthleticsAdmin |
| POST | `/permit-applications/{id}/respond` | Answer an information request | OrgCoordinator |
| GET | `/permits` | List permits with filters | Any authenticated role |
| GET | `/permits/{id}` | Get a permit | Any authenticated role |
| POST | `/permits/{id}/confirm` | Confirm a RESERVED permit | OrgCoordinator |
| POST | `/permits/{id}/cancel` | Cancel a permit with notice-tier penalty and waterfall | OrgCoordinator, AthleticsAdmin |
| POST | `/permits/{id}/check-in` | Record attendance for a CONFIRMED permit | FieldSupervisor |
| POST | `/permits/{id}/mark-no-show` | Mark a CONFIRMED permit as a no-show | FieldSupervisor |
| POST | `/permits/{id}/reschedule` | Reschedule a RAINED_OUT permit (OCC-guarded) | OrgCoordinator, AthleticsAdmin |
| POST | `/permits/{id}/revoke` | Revoke a permit under a fault code | AthleticsAdmin |
| POST | `/permits/{id}/settle` | Settle a checked-in CONFIRMED permit into COMPLETED | FieldSupervisor |
| POST | `/field-closures` | Create a closure, cascading rain-outs | FieldSupervisor |
| GET | `/field-closures` | List closures with filters | Any authenticated role |
| GET | `/field-closures/{id}` | Get a closure | Any authenticated role |
| POST | `/field-closures/{id}/lift` | Lift an ACTIVE closure | FieldSupervisor |
| GET | `/invoices` | List invoices with filters | Any authenticated role |
| GET | `/invoices/{id}` | Get an invoice | Any authenticated role |
| POST | `/invoices/{id}/issue` | Issue a DRAFT invoice | FinanceClerk |
| POST | `/invoices/{id}/void` | Void an invoice with no payments | FinanceClerk |
| POST | `/invoices/{id}/payments` | Record a cleared payment | FinanceClerk |
| POST | `/invoices/{id}/refunds` | Create a refund; large refunds pend approval | FinanceClerk |
| POST | `/invoices/{id}/adjustments` | Post a signed manual adjustment (OCC-guarded) | FinanceClerk |
| GET | `/payments` | List payments with filters | Any authenticated role |
| GET | `/payments/{id}` | Get a payment | Any authenticated role |
| POST | `/payments/{id}/approve` | Approve a PENDING_APPROVAL refund | AthleticsAdmin |
| GET | `/strike-records` | List strike records with filters | Any authenticated role |
| GET | `/strike-records/{id}` | Get a strike record | Any authenticated role |
| POST | `/strike-records/{id}/rescind` | Rescind an ACTIVE strike | AthleticsAdmin |
| GET | `/usage-ledgers` | List usage ledgers with filters | Any authenticated role |
| GET | `/usage-ledgers/{id}` | Get a usage ledger | Any authenticated role |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 where the guarded workflow lives; this table is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_ORG_OWNERSHIP` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ORGANIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_FEE_SCHEDULE_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_CLOSURE_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STRIKE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_PERMIT_STATE` | 409 Conflict |
| `ERR_INVALID_APPLICATION_STATE` | 409 Conflict |
| `ERR_INVALID_WINDOW_STATE` | 409 Conflict |
| `ERR_INVALID_INVOICE_STATE` | 409 Conflict |
| `ERR_INVALID_CLOSURE_STATE` | 409 Conflict |
| `ERR_INVALID_SCHEDULE_STATE` | 409 Conflict |
| `ERR_INVALID_PAYMENT_STATE` | 409 Conflict |
| `ERR_INVALID_STRIKE_STATE` | 409 Conflict |
| `ERR_ORG_SUSPENDED` | 409 Conflict |
| `ERR_FACILITY_CLOSED` | 409 Conflict |
| `ERR_HEADCOUNT_EXCEEDS_CAPACITY` | 409 Conflict |
| `ERR_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_WINDOW_NOT_YET_OPEN` | 409 Conflict |
| `ERR_SLOT_IN_PAST` | 409 Conflict |
| `ERR_RESCHEDULE_HORIZON_EXCEEDED` | 409 Conflict |
| `ERR_NO_SHOW_NOT_YET` | 409 Conflict |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CHECKIN_REQUIRED` | 409 Conflict |
| `ERR_INVALID_TIME_RANGE` | 409 Conflict |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_LIGHTS_BUFFER_OVERLAP` | 409 Conflict |
| `ERR_PRIME_CAP_EXCEEDED` | 409 Conflict |
| `ERR_TURF_REST_CAP_EXCEEDED` | 409 Conflict |
| `ERR_RESCHEDULE_LIMIT_REACHED` | 409 Conflict |
| `ERR_DEPOSIT_NOT_PAID` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_INVOICE_HAS_PAYMENTS` | 422 Unprocessable Entity |
