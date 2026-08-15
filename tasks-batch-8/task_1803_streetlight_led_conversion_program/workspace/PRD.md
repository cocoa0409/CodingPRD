# Streetlight LED Conversion API — Product Requirements Document

## 1. Introduction

Municipalities replacing legacy streetlighting with LED luminaires run a program that is part construction project, part tariff negotiation, and part regulatory audit. Poles must be inventoried and their existing wattages verified; conversion work must be scheduled into crew routes that respect traffic-control constraints and weekly overtime rules; the utility's unmetered billing must be re-rated as each fixture changes; outages reported by the public carry response-time commitments; removed fixtures must be weighed, manifested, and sold for scrap under environmental rules; and the energy savings that justified the program must be verified so that incentive rebates can be claimed against a fiscal-year cap.

This document specifies the Streetlight LED Conversion API, the system of record for that program, and is written for the engineers who will implement it. The API is mounted under `/streetlights` and manages the full conversion lifecycle — from a draft program budget through district zoning, pole audits, route planning, work-order dispatch and quality control, monthly unmetered billing, outage repair, salvage settlement, and finally savings attestation — under a segregation-of-duties role model in which the person who performs work is never the person who certifies it.

Two structural commitments shape everything that follows. First, money moves only through named, auditable postings: a single program budget ledger absorbs labor estimates, actual labor costs, salvage settlements, and rebate credits, and every posting is traceable to one business event. Second, billing is derived rather than entered: monthly charges are computed from pole wattage state and rate-schedule windows, so a retroactive audit correction or a mid-month conversion automatically re-rates what the utility would otherwise have billed stale.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which the user acts. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (403).

Seven roles exist, spelled exactly as follows:

- `ProgramManager` — the municipal program office. Creates, activates, and closes programs; creates districts, poles, crews, routes, and route stops; releases, suspends, resumes, and cancels routes; skips stops; accepts and disputes wattage audits; cancels work orders; triages and dispatches outage tickets; creates salvage batches and adds items to them; prepares and revises savings reports; requests compliance exceptions; and operates the logical clock.
- `FieldSupervisor` — a crew supervisor who submits and resubmits wattage audits, dispatches, completes, and fails work orders, and resolves assigned outage tickets. When `X-User-Role` is `FieldSupervisor`, `X-User-ID` is the `id` of the acting Crew; ownership checks on any resource that references a Crew compare the resource's foreign-key field to `X-User-ID` — concretely, a work order's `crew_id` at dispatch, completion, and failure, and a ticket's `assigned_crew_id` at resolution — and a mismatch is rejected with `ERR_FORBIDDEN`.
- `QaInspector` — an independent quality inspector who passes or fails completed work. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `qc_by_user_id` on the work order but does not compare it to any entity's `id`. Segregation of duties forbids an inspector from deciding QC on work they themselves completed.
- `BillingAnalyst` — the utility billing liaison: rate schedules, tariff accounts, line generation, period close, account freeze and unfreeze, salvage settlement, and nameplate attestation for utility-owned poles. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `ComplianceOfficer` — dark-sky and environmental compliance: approves or denies compliance exceptions and seals, manifests, or rejects salvage batches. `X-User-ID` is an opaque operator identifier, recorded as `decided_by_user_id` where the scaffold of a decision requires it, and never compared to any entity's `id`.
- `CitizenReporter` — a public portal user who reports outages and verifies or reopens resolutions. `X-User-ID` is an opaque operator identifier; the server records it as `reporter_user_id` on the ticket at creation, and the verify and reopen operations compare `X-User-ID` against that recorded reporter, rejecting anyone else with `ERR_FORBIDDEN`.
- `Auditor` — an external savings verifier who attests or rejects submitted savings reports, never their own submissions. `X-User-ID` is an opaque operator identifier, recorded as `attested_by_user_id` at attestation.

All seven roles may call every read endpoint, and every authenticated role may materialize compliance-exception expiry; the write operations enumerated above are exclusive to the roles named.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`. Unless a listing states its own ordering in §3, every list endpoint sorts by `created_at` ascending.

### 2.4. Resource Identity, Timestamps, Versioning, and the Logical Clock

Every resource carries four common properties: `id`, a server-minted UUID with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps with three fractional digits; and `version`, an integer that increments by exactly one on every mutation of that resource. All entity types in this system carry the full common-field set — none omits `updated_at` or `version`. Certain cascades deliberately bump a parent's `version` (notably the program's) even though the client's request targeted a child; those bumps are called out in §3 where they occur, and they are what the optimistic-concurrency fields of §2.8 observe.

The system never reads wall-clock time. All date and datetime derivations — billing periods, SLA measurement, in-service dates, route and rate window checks, reopen windows, exception expiry — read a server-side logical clock whose value before it is ever set is exactly 2026-08-01T00:00:00Z. A `ProgramManager` advances the clock through an administrative capability that accepts a `to_iso8601` instant and returns the new `current_utc`; the logical clock never falls back to wall-clock time.

### 2.5. Monetary Precision and the Program Budget Ledger

All money is integer cents. Where a computation produces a fraction, the rounding rule is round-half-up, applied at exactly the steps each calculation in §3 names — never banker's rounding, never truncation, and the order of rounding versus summation is part of each rule's contract. Kilowatt-hour quantities are rounded half-up to three decimal places, and fixture weights are carried to one decimal place.

A program's `budget_balance_cents` is initialized to `program_budget_cents` at creation and thereafter evolves only through these postings — conceptually, the original budget minus outstanding estimates and reconciled labor, plus salvage settlements and attested rebate credits:

- Dispatching a work order from `PENDING` debits `estimated_labor_cost_cents`.
- Dispatching a work order from `REWORK_PENDING` posts nothing; a work order carries a single estimate for its lifetime.
- Completing a work order debits the difference between `labor_cost_cents` and the outstanding estimate when the estimate has not yet been reconciled, and debits the full `labor_cost_cents` when it has; either way the completion marks the estimate reconciled.
- Cancelling a `DISPATCHED` work order credits back `estimated_labor_cost_cents` while the estimate is still outstanding; cancelling from `PENDING` or `REWORK_PENDING` posts nothing.
- Settling a salvage batch credits `settlement_value_cents`.
- Attesting a savings report credits `attested_credit_cents` — exactly once, at the moment of attestation.

The compensating-pair invariant is part of the contract: a dispatch from `PENDING` followed by a cancel from `DISPATCHED` leaves `budget_balance_cents` exactly unchanged, and for a salvage batch the settle and reject paths never both post.

### 2.6. Wattage Tiers, Dark-Sky CCT Caps, and Shielding Policy

A pole's `billing_wattage` is its `led_wattage` once `led_in_service_date` is set, and its `effective_wattage` before that. From `billing_wattage` the system derives `wattage_tier`: `T1` below 100 watts, `T2` from 100 up to 199, `T3` from 200 to 299, `T4` from 300 to 449, and `T5` at 450 watts or more. Lower bounds are inclusive — exactly 100 watts is `T2`, exactly 200 is `T3`, exactly 300 is `T4`, and exactly 450 is `T5`.

Dark-sky policy is fixed per district by its `zone`. The district's `cct_cap_kelvin` is 3000 for `RESIDENTIAL`, 4000 for `ARTERIAL`, 2700 for `DOWNTOWN`, and 2200 for `RURAL`. Its `full_cutoff_required` flag is true in `RESIDENTIAL` and `RURAL` districts and false in `ARTERIAL` and `DOWNTOWN` districts. Both values are derived at district creation and are enforced later at work-order dispatch (§3.4).

### 2.7. Calendar Windows: Crew Routes and Tariff Rate Schedules

Two window disciplines coexist and must not be conflated.

Crew route windows are closed intervals. Both `window_start_date` and `window_end_date` are inclusive, `window_end_date` must not precede `window_start_date`, and two non-`CANCELLED` routes assigned to the same crew may not share a single calendar day — routes whose windows merely touch on the same day are in conflict, and the second creation is rejected with `ERR_ROUTE_WINDOW_OVERLAP`.

Rate schedule windows are half-open: `effective_from` is inclusive, `effective_until` is exclusive, and a null `effective_until` means the window is open-ended; when present, `effective_until` must be later than `effective_from`. Two schedules of the same program and ownership class overlap when each window's start falls before the other's end; filing a schedule whose window so overlaps a `FILED` or `EFFECTIVE` sibling is rejected with `ERR_RATE_WINDOW_OVERLAP`, while pure adjacency — one window's `effective_until` equal to the other's `effective_from`, or vice versa — is allowed.

### 2.8. Optimistic Concurrency Control

Exactly two write endpoints carry a version field; no other endpoint takes one.

A request to create a wattage audit (`POST /streetlights/poles/{poleId}/audits`) must carry `expected_pole_version`, the client's last observed `version` of the target pole. If the pole's current `version` has advanced past that value — for example because an earlier audit submission or acceptance already bumped it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Audit submission otherwise succeeds under natural product semantics whenever no other audit is pending, so this version check is the only rejection that distinguishes a stale client's request.

A request to create a savings report (`POST /streetlights/savings-reports`) must likewise carry `expected_program_version` matching the program's current `version`. Creating a report legitimately supersedes the prior `DRAFT` or `REJECTED` report of the same period (§3.8), so a create issued with a fresh version would itself succeed; only a mismatched `expected_program_version` is rejected, again with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Nested Resources and Identifier Validation

Resource identifiers in a URL path are validated left to right, and only after the path checks pass are foreign-key identifiers in the request body validated, in input order. Each missing resource yields its own 404: an unknown program id yields `ERR_PROGRAM_NOT_FOUND`, district `ERR_DISTRICT_NOT_FOUND`, pole `ERR_POLE_NOT_FOUND`, audit `ERR_AUDIT_NOT_FOUND`, crew `ERR_CREW_NOT_FOUND`, route `ERR_ROUTE_NOT_FOUND`, route stop `ERR_STOP_NOT_FOUND`, work order `ERR_WORK_ORDER_NOT_FOUND`, rate schedule `ERR_RATE_SCHEDULE_NOT_FOUND`, tariff account `ERR_ACCOUNT_NOT_FOUND`, billing line `ERR_BILLING_LINE_NOT_FOUND`, outage ticket `ERR_TICKET_NOT_FOUND`, salvage batch `ERR_BATCH_NOT_FOUND`, salvage item `ERR_SALVAGE_ITEM_NOT_FOUND`, savings report `ERR_REPORT_NOT_FOUND`, and compliance exception `ERR_EXCEPTION_NOT_FOUND`.

### 2.10. Validation Pipeline Order

Every mutating request passes the same ordered pipeline, and a failure at any stage short-circuiting the rest — so when several rules could fire on one request, the earliest stage decides the error the caller sees:

1. Authentication: the `X-User-ID` and `X-User-Role` headers are present and the role is declared, else `ERR_UNAUTHENTICATED`.
2. Request shape: the body parses; required fields are present; types match; enum values are valid; date strings are ISO; `window_end_date` is not before `window_start_date`; a provided `weight_lbs` is positive with at most one decimal place; a retire payload's `effective_until` is present, later than `effective_from`, and not before the current date — any failure is `ERR_INVALID_REQUEST`.
3. Role permission: the role may call this endpoint at all, else `ERR_FORBIDDEN`.
4. Existence: path and body identifiers resolve, per §2.9.
5. Ownership identity: crew and reporter checks per §2.1, else `ERR_FORBIDDEN`.
6. Segregation of duties: QC decisions and report attestation or rejection may not be self-approved, else `ERR_SEGREGATION_OF_DUTIES`.
7. Staleness: the OCC version fields of §2.8, else `ERR_STALE_VERSION`.
8. Program lifecycle: child-resource mutations require an `ACTIVE` program, else `ERR_PROGRAM_NOT_ACTIVE`; the program's own activate and close endpoints are exempt from this stage.
9. Target state: the target resource's own state must permit the transition, and where several state rules apply, the target resource's state is checked before related-entity state — at dispatch, the work order's state is checked first, then the route's, then the stop's. The state-stage errors are `ERR_AUDIT_NOT_SUBMITTED`, `ERR_ROUTE_NOT_PLANNED`, `ERR_ROUTE_SUSPENDED`, `ERR_ROUTE_NOT_SUSPENDED`, `ERR_ROUTE_STILL_BLOCKED`, `ERR_STOP_NOT_PENDING`, `ERR_STOP_BLOCKED`, `ERR_WORK_ORDER_NOT_DISPATCHABLE`, `ERR_WORK_ORDER_NOT_COMPLETABLE`, `ERR_WORK_ORDER_NOT_CANCELLABLE`, `ERR_QC_NOT_AWAITING`, `ERR_ACCOUNT_NOT_OPEN`, `ERR_TICKET_NOT_OPEN`, `ERR_TICKET_NOT_TRIAGED`, `ERR_TICKET_NOT_DISPATCHED`, `ERR_TICKET_NOT_RESOLVED`, `ERR_BATCH_NOT_ACCUMULATING`, `ERR_BATCH_NOT_SEALED`, `ERR_BATCH_NOT_MANIFESTED`, `ERR_REPORT_NOT_DRAFT`, `ERR_REPORT_NOT_SUBMITTED`, `ERR_EXCEPTION_NOT_PENDING`, `ERR_RATE_SCHEDULE_NOT_DRAFT`, `ERR_RATE_SCHEDULE_NOT_FILED`, `ERR_RATE_SCHEDULE_NOT_EFFECTIVE`, `ERR_POLE_EXEMPT`, `ERR_ROUTES_STILL_ACTIVE`, and `ERR_POLE_NOT_AUDIT_CLEARED`, each bound in §3 to the transition it guards. (A route-terminal rejection, `ERR_ROUTE_TERMINAL`, is reserved at this stage but is never observed in practice: on a `CLOSED` or `CANCELLED` route every linked work order is already terminal, so the work-order state check always fires first.)
10. Dark-sky CCT, then shielding: `ERR_CCT_EXCEEDS_ZONE_CAP` before `ERR_SHIELDING_REQUIRED`.
11. Temporal rules, in this relative order: crew route-window overlap (`ERR_ROUTE_WINDOW_OVERLAP`), rate-window overlap (`ERR_RATE_WINDOW_OVERLAP`), stop-add after window start (`ERR_ROUTE_WINDOW_PAST`), exception window past (`ERR_EXCEPTION_WINDOW_PAST`), reopen window expired (`ERR_REOPEN_WINDOW_EXPIRED`).
12. Uniqueness, capacity, and business constraints, in this relative order: `ERR_DUPLICATE_POLE_NUMBER`, `ERR_DUPLICATE_ACCOUNT`, `ERR_DUPLICATE_SEQUENCE`, `ERR_DUPLICATE_STOP`, `ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_EMPTY_ROUTE`, `ERR_ACTIVE_WORK_ORDER_EXISTS`, `ERR_INSUFFICIENT_WATTAGE_REDUCTION`, `ERR_AUDIT_ALREADY_PENDING`, `ERR_EMPTY_BATCH`, `ERR_UNWEIGHED_ITEMS`, `ERR_REPORT_PERIOD_FINALIZED`, `ERR_REPORT_PERIOD_OPEN`, `ERR_NO_EFFECTIVE_RATE_SCHEDULE`.
13. Referential rules, in this relative order: `ERR_CROSS_DISTRICT_STOP`, `ERR_AUDIT_NOT_PERMITTED_UTILITY`, `ERR_ATTEST_NOT_PERMITTED_MUNICIPAL`; the salvage batching check `ERR_SALVAGE_ITEM_ALREADY_BATCHED` sits immediately after them.
14. The fiscal gate is evaluated last: `ERR_PROGRAM_BUDGET_EXCEEDED`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program: Budgets, Districts, and the Pole Inventory

A `ProgramManager` opens a conversion program by supplying its `program_name`, the total appropriation `program_budget_cents`, the fiscal-year incentive ceiling `fy_rebate_cap_cents`, and the `rebate_cents_per_kwh` rate at which verified savings convert to credits; all three monetary inputs must be greater than zero. The program is born `DRAFT`, its `budget_balance_cents` starts equal to `program_budget_cents`, and its computed rollups — `current_billing_run_estimated_cents`, `converted_pole_count`, and `pending_salvage_item_count` — start at zero. Activation carries the program `DRAFT` → `ACTIVE` and bumps its `version`; closure carries `ACTIVE` → `CLOSED`, the terminal state, and is refused with `ERR_ROUTES_STILL_ACTIVE` while any of the program's routes is in a state other than `CLOSED` or `CANCELLED`. Every child-resource mutation in the system requires the program to be `ACTIVE` — while `DRAFT` or `CLOSED`, such mutations fail with `ERR_PROGRAM_NOT_ACTIVE`. A program summary read returns the live rollups `budget_balance_cents`, `current_billing_run_estimated_cents`, `converted_pole_count`, `pending_salvage_item_count`, and `status`; `converted_pole_count` counts the program's poles whose `led_in_service_date` is set, and `pending_salvage_item_count` counts salvage items sitting in the unbatched pool. The program listing accepts an optional `status` filter.

Districts carve the service territory. Creating one takes `program_id`, a `district_name` that must be unique within the program, and a `zone` of `RESIDENTIAL`, `ARTERIAL`, `DOWNTOWN`, or `RURAL`; the dark-sky derivatives `cct_cap_kelvin` and `full_cutoff_required` follow from the zone per §2.6. The district listing filters by `program_id` and `zone`.

Poles are registered under a district with `district_id`, a `pole_number` that must be unique across the whole program regardless of district (a collision is `ERR_DUPLICATE_POLE_NUMBER`), an `ownership_type` of `MUNICIPAL` or `UTILITY_OWNED`, the `fixture_class` of the existing fixture — `COBRA_HEAD`, `FLOOD`, `POST_TOP`, or `DECORATIVE`, later copied onto the salvage record when the fixture comes down — and the `nameplate_wattage` of the existing luminaire, which must be greater than zero. A pole is born `SURVEYED`, its `effective_wattage` starts equal to `nameplate_wattage`, and its lifecycle runs through `AUDIT_CLEARED`, `SCHEDULED`, `CONVERTED`, possibly `REWORK`, `VERIFIED`, and the repair state `UNDER_REPAIR`, with `EXEMPT` as the terminal alternative. Until a conversion completes, the pole's `pre_conversion_wattage`, `led_wattage`, and `led_in_service_date` are all null, and `pre_repair_status` is null outside a repair episode. The pole listing filters by `district_id`, `status`, and `ownership_type`.

Ownership selects the audit path. A `MUNICIPAL` pole earns `AUDIT_CLEARED` through the wattage-audit cycle of §3.2. A `UTILITY_OWNED` pole instead takes nameplate attestation: a `BillingAnalyst` attests the nameplate and the pole moves `SURVEYED` → `AUDIT_CLEARED` with no audit at all; attempting that attestation on a `MUNICIPAL` pole is rejected with `ERR_ATTEST_NOT_PERMITTED_MUNICIPAL`.

### 3.2. Wattage Audits, Nameplate Attestation, and the Retroactive Adjustment

A `FieldSupervisor` submits a wattage audit against a pole with a payload of `audited_wattage` — the field-measured draw, greater than zero — and optional free-text `auditor_notes` defaulting to empty, plus the OCC field `expected_pole_version` per §2.8. Audits exist only for `MUNICIPAL` poles: submitting one against a `UTILITY_OWNED` pole is `ERR_AUDIT_NOT_PERMITTED_UTILITY`. An `EXEMPT` pole rejects both submission and acceptance with `ERR_POLE_EXEMPT`, and a pole may hold at most one `SUBMITTED` audit at a time (`ERR_AUDIT_ALREADY_PENDING`). The new audit is born `SUBMITTED` with `revision_count` zero and `decided_by_user_id` null, and the act of submission itself bumps the pole's `version` by one — which is precisely what a second, stale client's `expected_pole_version` will trip over. The audit listing filters by `pole_id` and `status`.

Acceptance belongs to the `ProgramManager` and requires the audit `SUBMITTED` (`ERR_AUDIT_NOT_SUBMITTED` otherwise, and the same error when a resubmission is attempted from a state other than `DISPUTED`). On acceptance the pole's `effective_wattage` becomes the `audited_wattage`; any previously `ACCEPTED` audit for the same pole is automatically `SUPERSEDED` (the audit's terminal state); a pole still `SURVEYED` advances to `AUDIT_CLEARED`; the retroactive billing adjustment below runs; and the pole's `version` bumps again.

Dispute moves `SUBMITTED` → `DISPUTED` and records the decider in `decided_by_user_id`. A disputed audit is not dead: the `FieldSupervisor` may resubmit it with a corrected `audited_wattage` (and fresh `auditor_notes`), which returns it `DISPUTED` → `SUBMITTED`, increments `revision_count`, and clears `decided_by_user_id` back to null.

The retroactive adjustment fires whenever acceptance changes a pole's `effective_wattage`. The pole's billing lines are walked in `period` ascending order, `created_at` ascending within a period. Each `ESTIMATED` `REGULAR` line is recomputed in place under the monthly-charge rule of §3.5 — its `charge_cents`, `billing_wattage`, and `tier` are rewritten. Each `BILLED` `REGULAR` line is recomputed with the new wattage basis while dates, the proration split, and the ownership variant stay unchanged; when the recomputed charge differs from the stored one, the old line becomes `SUPERSEDED` and a new `ADJUSTMENT` line is created — born `BILLED`, its `supersedes_line_id` pointing at the old line, billing the same `period`, carrying `charge_cents` equal to the signed delta — and when the charge is unchanged the line is left untouched rather than churned. Afterwards the account's `current_period_estimated_cents` and `ytd_billed_cents` and the program's `current_billing_run_estimated_cents` are recomputed.

### 3.3. Crews, Conversion Routes, and Stop Planning

A crew is created with `program_id`, a `crew_name`, the `base_stops_per_shift` ceiling on stops one shift can complete, and the straight-time `hourly_rate_cents`; both numbers must be greater than zero. The crew listing filters by `program_id`.

A conversion route is born `PLANNED` from `district_id`, the assigned `crew_id`, the inclusive `window_start_date` and `window_end_date`, and `traffic_control_required`, which decides whether each shift carries 60 minutes of mobilization overhead instead of 30. The same-crew closed-window conflict rule of §2.7 applies at creation. A route's computed face includes `stop_count` — stops in `PENDING`, `BLOCKED`, or `COMPLETE` (skipped stops do not count) — `blocked_stop_count`, `total_workload_minutes` as the sum of `stop_minutes` over non-`SKIPPED` stops, and `required_shifts`, the workload divided by per-shift capacity rounded up. Its lifecycle runs `PLANNED` → `RELEASED` → `IN_PROGRESS`, with `SUSPENDED` as a detour and `CLOSED` or `CANCELLED` terminal. The route listing filters by `district_id`, `crew_id`, and `status`.

Stops join a route only while it is `PLANNED` (`ERR_ROUTE_NOT_PLANNED`) and only while its `window_start_date` has not yet passed relative to the logical clock (`ERR_ROUTE_WINDOW_PAST`). The payload carries `pole_id`, a `sequence_number` greater than zero that is unique within the route (`ERR_DUPLICATE_SEQUENCE`), and a `difficulty_class` of `STANDARD`, `HEAVY`, or `COMPLEX`, from which `stop_minutes` derives: 45 for `STANDARD`, 75 for `HEAVY`, 120 for `COMPLEX`. The pole must live in the route's own district (`ERR_CROSS_DISTRICT_STOP`), must be `AUDIT_CLEARED` — an `EXEMPT` pole draws `ERR_POLE_EXEMPT`, a pole in any other state `ERR_POLE_NOT_AUDIT_CLEARED` — and may not already hold a `PENDING` stop on any non-terminal route (`ERR_DUPLICATE_STOP`). A successful add moves the pole `AUDIT_CLEARED` → `SCHEDULED` and recomputes the route counters.

Every candidate stop is also capacity-checked, incrementally, including the candidate itself. Let the workload be the sum of `stop_minutes` over all non-`SKIPPED` stops including the candidate; mobilization is 60 minutes per shift when the route requires traffic control and 30 otherwise; a shift holds 480 minutes. The `required_shifts` figure is the workload divided by the shift's net minutes — 480 minus mobilization — rounded up, and the window length in days counts both endpoints inclusively. The add is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED` when the required shifts exceed the window days, or when the stop count including the candidate divided by the required shifts, rounded up, exceeds the crew's `base_stops_per_shift`. Both checks use post-add values, and either can bind while the other passes. The stop listing filters by `route_id`, `pole_id`, and `status`, and orders stops by route creation, then `sequence_number` ascending within each route.

Release moves `PLANNED` → `RELEASED` — from any other state the release is `ERR_ROUTE_NOT_PLANNED` — and requires at least one counted stop (`ERR_EMPTY_ROUTE`). Releasing auto-creates one work order per non-`SKIPPED` stop: execution `PENDING`, QC `NONE`, `stop_minutes` copied from the stop's difficulty minutes, bound to its `route_id`, `stop_id`, and `pole_id`, crew taken from the route, `ticket_id` null, `is_replacement` false, `est_reconciled` false, and both `labor_cost_cents` and `completed_at` null until a completion.

Suspension has two doors into the same state. A `ProgramManager` may suspend an `IN_PROGRESS` route manually — suspending from any other state, or resuming a route that is not `SUSPENDED`, is `ERR_ROUTE_NOT_SUSPENDED` — and the system suspends automatically whenever a route's `blocked_stop_count` changes while the route is `IN_PROGRESS` with at least one counted stop: if twice the blocked count is greater than or equal to `stop_count`, the route suspends itself. The comparison is made on the doubled count, so exactly half blocked suspends (two blocked of four does) while one blocked of three does not. Resume moves `SUSPENDED` → `IN_PROGRESS` and is never automatic; it requires twice the blocked count to be strictly less than `stop_count`, failing with `ERR_ROUTE_STILL_BLOCKED` otherwise.

Cancellation is available from `PLANNED`, `RELEASED`, `IN_PROGRESS`, or `SUSPENDED`. From `PLANNED` the cascade skips every `PENDING` or `BLOCKED` stop and returns each linked pole still `SCHEDULED` to `AUDIT_CLEARED`. From the three later states the cascade additionally cancels every non-terminal work order, refunding outstanding estimates per the ledger of §2.5. A route also closes itself: once every stop is `COMPLETE` or `SKIPPED`, no linked work order remains in `PENDING`, `DISPATCHED`, `FAILED`, or `REWORK_PENDING`, and no work order stands at `AWAITING_QC`, the route moves `IN_PROGRESS` → `CLOSED`.

An individual `PENDING` stop may be skipped by a `ProgramManager` provided no `DISPATCHED` or `COMPLETED` work order is linked to it (`ERR_STOP_NOT_PENDING`); skipping cancels the linked `PENDING` work order with no refund — a `PENDING` order never carried a debit — and returns the pole `SCHEDULED` → `AUDIT_CLEARED`.

### 3.4. Dispatch, Execution, Labor Costing, and Quality Control

Work orders carry two parallel status dimensions on one row: `execution_status` (`PENDING`, `DISPATCHED`, `COMPLETED`, `FAILED`, `REWORK_PENDING`, or terminally `CANCELLED`) and `qc_status` (`NONE`, `AWAITING_QC`, or terminally `QC_PASSED`, with `QC_FAILED` as the rework trigger). Every completion moves the QC dimension to `AWAITING_QC` — from `NONE` on a first completion, from `QC_FAILED` on a rework completion — and QC decisions move `AWAITING_QC` to `QC_PASSED` or `QC_FAILED`.

Dispatch moves `PENDING` → `DISPATCHED`, or `REWORK_PENDING` → `DISPATCHED` for rework, and belongs to the `FieldSupervisor` whose `X-User-ID` equals the work order's `crew_id` (`ERR_FORBIDDEN`). The payload specifies the fixture going in: `new_fixture_wattage` and `new_cct_kelvin`, both greater than zero, and `shielding` of `FULL_CUTOFF`, `SEMI_CUTOFF`, or `NONE`. The gates fire in the pipeline order of §2.10. The work order itself must be dispatchable (`ERR_WORK_ORDER_NOT_DISPATCHABLE`). The route, when the order is route-linked, must be `RELEASED` or `IN_PROGRESS`; a `SUSPENDED` route rejects with `ERR_ROUTE_SUSPENDED`, while on a `CLOSED` or `CANCELLED` route every linked work order is already terminal, so the work-order state check always fires first and the route-terminal rejection is never observed. The linked stop, when present, must be `PENDING` (`ERR_STOP_BLOCKED`). Then the dark-sky gate: `new_cct_kelvin` must not exceed the district's `cct_cap_kelvin` unless the pole holds an `APPROVED` `CCT_WAIVER` whose `requested_cct_kelvin` covers the requested value and whose `valid_until` has not passed — a waiver past its `valid_until` is treated as expired at dispatch even before expiry is materialized (`ERR_CCT_EXCEEDS_ZONE_CAP`). Then shielding: in a district where `full_cutoff_required` is true, only `FULL_CUTOFF` is accepted (`ERR_SHIELDING_REQUIRED`). Then exclusivity: no other work order for the same pole may be `DISPATCHED` (`ERR_ACTIVE_WORK_ORDER_EXISTS`). Then the wattage-reduction gate: five times `new_fixture_wattage` must not exceed four times the pole's `effective_wattage` — at least a twenty percent reduction, with exactly eighty percent of the old wattage allowed (`ERR_INSUFFICIENT_WATTAGE_REDUCTION`). Finally the fiscal gate: the straight-time estimate `estimated_labor_cost_cents` — the crew's `hourly_rate_cents` multiplied by the order's `stop_minutes` and divided by 60, rounded half-up — must not exceed the program's `budget_balance_cents` (`ERR_PROGRAM_BUDGET_EXCEEDED`). Dispatch from `PENDING` debits that estimate (§2.5), stores the fixture fields, moves the route `RELEASED` → `IN_PROGRESS` on the route's first dispatch, and bumps the program's `version`; dispatch from `REWORK_PENDING` updates the fixture fields from the new payload and posts nothing.

Completion moves `DISPATCHED` → `COMPLETED` under the same crew-ownership rule (`ERR_FORBIDDEN`); completing or failing from any state other than `DISPATCHED` is `ERR_WORK_ORDER_NOT_COMPLETABLE`. The order stamps `completed_at` from the logical clock, records `performed_by_user_id` as the completer's `X-User-ID` — for a `FieldSupervisor`, that is their crew's id — and moves QC to `AWAITING_QC`. The overtime-aware `labor_cost_cents` is computed as below and reconciled against the estimate per §2.5, flipping `est_reconciled` to true. A conversion completion moves the pole into `CONVERTED` — from `SCHEDULED` on first conversion, or `REWORK` → `CONVERTED` on rework — snapshots `pre_conversion_wattage` from `effective_wattage` at the first completion only, and records `led_wattage` from the order's `new_fixture_wattage` and `led_in_service_date` as the completion date, an ISO calendar date; rework refreshes `led_wattage` and `led_in_service_date` without re-taking the snapshot. A replacement completion refreshes the pole's wattage and date the same way but leaves the pole `UNDER_REPAIR` pending QC. At the first completion of each work order only — the moment `est_reconciled` flips — exactly one salvage item is auto-created for the removed fixture: unbatched with `batch_id` null, `fixture_class` copied from the pole, `weight_lbs` zero, `mercury_flag` false; rework re-completions create none. Any `ESTIMATED` billing lines for the pole in open periods re-rate under §3.5, the linked stop moves `PENDING` → `COMPLETE`, route auto-close is evaluated, and the program's `version` bumps.

Labor costing is overtime-aware. The weekly accumulator scopes to the crew's completed work orders — execution `COMPLETED` regardless of QC state — whose `completed_at` falls in the same ISO-8601 week as this completion, the week running Monday 00:00 UTC through Sunday 24:00 UTC. The processing order is `completed_at` ascending, then the route's `window_start_date` ascending, then the stop's `sequence_number` ascending; ties on `completed_at` are fully broken because a crew's route windows never share a calendar day and `sequence_number` is unique per route, and replacement orders, which carry no window, sort after dated orders at the same instant, ordered among themselves by their ticket's creation time. The order's `cumulative_week_minutes_before` is the sum of `stop_minutes` over that ordered set excluding this completion. Against the weekly overtime threshold of 2400 minutes: if the prior total is already at or beyond 2400, the entire order bills as overtime; if the prior total plus this order's minutes crosses 2400, only the minutes beyond the threshold are overtime and the rest bill straight-time; otherwise the whole order bills straight-time. Boundary semantics are exact — a prior total of exactly 2400 makes the whole stop overtime, while a running total landing exactly on 2400 bills no overtime on that stop. The order's `overtime_minutes` records the excess, and `labor_cost_cents` is the straight-time minutes at `hourly_rate_cents` per hour — rate times minutes divided by 60, rounded half-up — plus the overtime minutes at one and a half times the rate, also divided by 60 and rounded half-up, the two rounded parts then summed.

Failure moves `DISPATCHED` → `FAILED`, moves no money — the estimate stays outstanding — and the system immediately re-queues the order `FAILED` → `PENDING` through an automatic retry.

Cancellation by a `ProgramManager` requires `PENDING`, `DISPATCHED`, or `REWORK_PENDING` (`ERR_WORK_ORDER_NOT_CANCELLABLE`). From `PENDING`, or from `DISPATCHED` with the outstanding-estimate refund of §2.5, the linked stop, if still `PENDING`, skips and the pole, if still `SCHEDULED`, returns to `AUDIT_CLEARED`. From `REWORK_PENDING` the linked stop skips if `PENDING` but the pole stays `REWORK` — an already-converted pole is never reverted by a cancel.

Quality control belongs to the `QaInspector`, requires execution `COMPLETED` with QC `AWAITING_QC` (`ERR_QC_NOT_AWAITING` otherwise, including a wrong QC state), and may not be decided by the user recorded as `performed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); `qc_by_user_id` records the decider on either verdict. A pass moves QC to `QC_PASSED`: a conversion order's pole goes `CONVERTED` → `VERIFIED`, while a replacement order returns its pole from `UNDER_REPAIR` — to `SCHEDULED` when `pre_repair_status` is `SCHEDULED`, returning the blocked stop to `PENDING` and recomputing route counters, and to `VERIFIED` when `pre_repair_status` was `CONVERTED`, `REWORK`, or `VERIFIED` — clearing `pre_repair_status` to null either way. A fail moves QC to `QC_FAILED`, execution `COMPLETED` → `REWORK_PENDING`, and a conversion order's pole `CONVERTED` → `REWORK`. The work-order listing filters by `route_id`, `pole_id`, `crew_id`, `stop_id`, `ticket_id`, `execution_status`, and `qc_status`, and orders by route `window_start_date` ascending, then stop `sequence_number` ascending, then `created_at` ascending.

### 3.5. Tariff Schedules, Unmetered Accounts, and Monthly Billing

A `BillingAnalyst` files the rate card. A rate schedule is created `DRAFT` with `program_id`, an `ownership_class` of `MUNICIPAL` or `UTILITY_OWNED`, the `effective_from` date, an optional `effective_until` (null for open-ended), and `tier_rates`, a map keyed by all five tiers `T1` through `T5`, each value a positive integer of cents per pole per month. Filing moves `DRAFT` → `FILED` (`ERR_RATE_SCHEDULE_NOT_DRAFT` from elsewhere) and runs the half-open overlap check of §2.7 against `FILED` and `EFFECTIVE` siblings of the same program and ownership class (`ERR_RATE_WINDOW_OVERLAP`). Activation moves `FILED` → `EFFECTIVE` (`ERR_RATE_SCHEDULE_NOT_FILED`). Retirement moves `EFFECTIVE` → `SUPERSEDED` (`ERR_RATE_SCHEDULE_NOT_EFFECTIVE`), requires a payload `effective_until` after `effective_from` and not before the current date (`ERR_INVALID_REQUEST`), and shortens the window to that value. The schedule listing filters by `program_id`, `ownership_class`, and `status`.

Unmetered accounts are one per district and ownership class: creating one takes `district_id`, the utility's `account_number` — unique within the program — and `ownership_class`, and a second `OPEN` or `FROZEN` account for the same district and class is refused with `ERR_DUPLICATE_ACCOUNT`. The account is born `OPEN`, and its `current_period` initializes to the logical clock's calendar month in `YYYY-MM` form. Freezing moves `OPEN` → `FROZEN` and unfreezing returns it; line generation and period close both require `OPEN` (`ERR_ACCOUNT_NOT_OPEN`). The account listing filters by `district_id`, `ownership_class`, and `status`.

Line generation sweeps the poles of the account's district and ownership class — `EXEMPT` poles excluded — and creates one `ESTIMATED` `REGULAR` billing line per pole for `current_period`, skipping any pole that already holds a non-`SUPERSEDED` `REGULAR` line for the period; the response reports `created_count` and `skipped_count`. Each line binds its `account_id`, `pole_id`, the `rate_schedule_id` used for its rate lookup, the billed `period`, and a `line_type` of `REGULAR`. If any eligible pole's ownership class has no covering schedule — one `EFFECTIVE` or `SUPERSEDED` whose half-open window covers the period's first day — the run fails atomically, creating nothing, with `ERR_NO_EFFECTIVE_RATE_SCHEDULE`. Afterwards the account's `current_period_estimated_cents` — the sum of `charge_cents` over its `ESTIMATED` `REGULAR` lines in `current_period` — and the program's `current_billing_run_estimated_cents`, the same quantity summed across all of the program's accounts, are recomputed.

The monthly unmetered charge works as follows. The period is the calendar month of the account's `current_period`, inclusive at both ends, D days long. The applicable schedule is the one for the program and the pole's ownership class, `EFFECTIVE` or `SUPERSEDED`, whose half-open window covers the period's first day. The old rate is that schedule's tier rate for the tier of the pole's `effective_wattage`; the new rate is the tier rate for the tier of `led_wattage` once converted. For a `MUNICIPAL` pole the month prorates daily: with no in-service date, or an in-service date after the period's end, the whole period bills the old rate with `billing_wattage` equal to `effective_wattage`; with an in-service date on or before the period's first day, the whole period bills the new rate with `billing_wattage` equal to `led_wattage`; otherwise the month splits — the old rate covers the days from the period start through the day before the in-service date, and the new rate covers the remaining days including the in-service day itself — each prorated part computed as its rate times its day count divided by D and rounded half-up individually, the parts then summed, with `billing_wattage` and `tier` reflecting the LED. For a `UTILITY_OWNED` pole the conversion month defers wholesale: with no in-service date or one after the period end, the old rate applies; with an in-service date within the period, the entire conversion period still bills the old rate at `effective_wattage` and the new rate applies only from the next period; with an in-service date before the period start, the new rate applies. A pole's `EXEMPT` status removes it from generation runs entirely.

Billing lines move `ESTIMATED` → `BILLED` when the period closes; re-rating rewrites an `ESTIMATED` line in place (`charge_cents`, `billing_wattage`, `tier`, `rate_schedule_id` recomputed); and the audit-driven supersede of §3.2 moves `BILLED` → `SUPERSEDED` with a compensating `ADJUSTMENT` line, born `BILLED`, carrying the signed delta. Closing the period moves the account's `ESTIMATED` lines of `current_period` to `BILLED`, recomputes `ytd_billed_cents` — the sum of `charge_cents` over `REGULAR` lines in `BILLED` or `SUPERSEDED` status plus all `ADJUSTMENT` lines, over periods in the calendar year of `current_period` — resets `current_period_estimated_cents` to zero, and advances `current_period` by one month. The line listing filters by `account_id`, `pole_id`, `rate_schedule_id`, `supersedes_line_id`, `period`, `status`, and `line_type`, and sorts by `period` ascending then `created_at` ascending.

### 3.6. Outage Tickets, Repair SLAs, and the UNDER_REPAIR Cycle

The public portal funnels outages into tickets with a lifecycle of `OPEN`, `TRIAGED`, `DISPATCHED`, `RESOLVED`, and then terminal `VERIFIED` or a reporter-driven `REOPENED` loop, with `DUPLICATE` as the other terminal state. A `CitizenReporter` reports by `pole_id` with free-text `description` and an optional `hazard_flag` defaulting to false; reports against an `EXEMPT` pole are refused with `ERR_POLE_EXEMPT`. The server stamps `reporter_user_id` from the caller and `reported_at` from the logical clock — the SLA clock's origin, which never resets. Duplicate detection runs at creation: if the pole already has a ticket in `OPEN`, `TRIAGED`, `DISPATCHED`, `RESOLVED`, or `REOPENED` (`VERIFIED` and `DUPLICATE` tickets do not count), the new ticket is created directly as `DUPLICATE` — terminal, carrying no `priority` or `sla_hours`, and it cannot be triaged — with `duplicate_of_ticket_id` pointing at the earliest-created candidate; with no candidates the ticket is created `OPEN` with `duplicate_of_ticket_id` null. A ticket's `priority` and `sla_hours` stay null until triage, `sla_breached` stays null until resolution, and `reopen_count` starts at zero. The ticket listing filters by `pole_id`, `duplicate_of_ticket_id`, `assigned_crew_id`, `status`, and `priority`.

Triage, by a `ProgramManager`, moves `OPEN` or `REOPENED` → `TRIAGED` (`ERR_TICKET_NOT_OPEN` otherwise) and fixes `priority` and `sla_hours`. A hazard-flagged ticket is `CRITICAL`; otherwise a pole in an `ARTERIAL` district tiered `T4` or `T5` is `CRITICAL`; otherwise an `ARTERIAL` pole or any pole tiered `T3`, `T4`, or `T5` is `HIGH`; everything else is `STANDARD`. The SLA is 24 hours for `CRITICAL`, 48 for `HIGH`, 96 for `STANDARD`. Dispatch, again the `ProgramManager`, moves `TRIAGED` → `DISPATCHED` (`ERR_TICKET_NOT_TRIAGED`) and binds the payload `crew_id` as `assigned_crew_id`.

Resolution belongs to the assigned crew — a `FieldSupervisor` whose `X-User-ID` must equal `assigned_crew_id` (`ERR_FORBIDDEN`) — and requires `DISPATCHED` (`ERR_TICKET_NOT_DISPATCHED`). The payload `resolution_code` is `LIGHT_OUT_FIXED`, `FIXTURE_REPLACED`, or `NO_FAULT_FOUND`; `resolved_at` stamps from the clock; and `sla_breached` is true only when the elapsed time from `reported_at` to `resolved_at` strictly exceeds `sla_hours` — landing exactly on the SLA is not a breach.

A resolution of `FIXTURE_REPLACED` fires the replacement cascade. The pole moves to `UNDER_REPAIR` with `pre_repair_status` recording where it came from — `SCHEDULED`, `CONVERTED`, `REWORK`, or `VERIFIED`. A replacement work order is created with execution `PENDING`, its `route_id` and `stop_id` null, its `crew_id` set to the resolving crew, its `ticket_id` bound to this ticket, `is_replacement` true, and a flat 75-minute `stop_minutes` basis. A `PENDING` stop referencing the pole moves to `BLOCKED`, the route's `blocked_stop_count` recomputes, and auto-suspension is evaluated. If the pole was already `UNDER_REPAIR` when another fixture-replacement resolution lands, its original `pre_repair_status` is retained rather than overwritten, a fresh replacement order is created under the resolving crew, and no stop transition occurs because the stop is already `BLOCKED` or absent.

The reporter alone closes the loop. Verification moves `RESOLVED` → `VERIFIED`; reopening moves `RESOLVED` → `REOPENED`; both require `X-User-ID` equal to `reporter_user_id` (`ERR_FORBIDDEN`) and a `RESOLVED` ticket (`ERR_TICKET_NOT_RESOLVED`). Reopening is allowed only within 72 hours of `resolved_at` — at exactly 72 hours it still succeeds, later it fails with `ERR_REOPEN_WINDOW_EXPIRED` — and it increments `reopen_count` by one, escalates `priority` exactly one level (`STANDARD` to `HIGH`, `HIGH` to `CRITICAL`, `CRITICAL` unchanged), and recomputes `sla_hours` from the escalated priority, while deliberately leaving `reported_at` untouched so the next resolution still measures from the original report. A reopened ticket is triaged again, re-asserting the escalated values.

### 3.7. Salvage, Settlement, and the Unbatched Pool

Removed fixtures accumulate as salvage. Each first completion of a work order drops one item into the program's unbatched pool (§3.4), and the item listing filters by `batch_id` — the literal value `null` selects the pool — plus `pole_id` and `fixture_class`.

A `ProgramManager` creates a batch, born `ACCUMULATING`, with `program_id` and a `batch_label` unique within the program, then moves items in one at a time by `salvage_item_id`, optionally declaring `weight_lbs` and `mercury_flag` (default false) at add time. The batch must be `ACCUMULATING` (`ERR_BATCH_NOT_ACCUMULATING`), the item currently unbatched (`ERR_SALVAGE_ITEM_ALREADY_BATCHED`), and a provided `weight_lbs` positive with at most one decimal place (`ERR_INVALID_REQUEST`). Adding binds the item's `batch_id`, records the declarations, and recomputes the batch's `item_count` and `total_weight_lbs`, the latter carried to one decimal. The batch listing filters by `program_id` and `status`.

Sealing belongs to the `ComplianceOfficer`, requires the batch `ACCUMULATING` (`ERR_BATCH_NOT_ACCUMULATING`) with at least one item (`ERR_EMPTY_BATCH`), and records the payload `contaminated_flag` marking PCB contamination. Manifesting requires `SEALED` (`ERR_BATCH_NOT_SEALED`) and every item weighed — any `weight_lbs` still zero fails with `ERR_UNWEIGHED_ITEMS` — then mints `manifest_code` as the prefix `MF-` followed by the batch label and computes the settlement value, with `settlement_value_cents` null until this point. That computation's order is pinned because the rounding is observable: for each fixture class, sum the batch's `weight_lbs` in that class, multiply by the class price per pound — 85 cents for `COBRA_HEAD`, 95 for `FLOOD`, 70 for `POST_TOP`, 110 for `DECORATIVE` — round half-up, subtract 300 cents for each mercury-flagged item of the class, and floor the class value at zero. The subtotal is the sum of the four already-rounded class values — round per class, then sum, never the reverse. When `contaminated_flag` is set, deduct fifteen percent of the subtotal, that deduction itself rounded half-up. Finally subtract the 4500-cent transport fee and floor at zero: the result is `settlement_value_cents`.

Settlement, by a `BillingAnalyst`, requires `MANIFESTED` (`ERR_BATCH_NOT_MANIFESTED`), credits `settlement_value_cents` to the program budget, and bumps the program's `version`, leaving the batch `SETTLED` and terminal. Rejection, by the `ComplianceOfficer`, is available from `SEALED` or `MANIFESTED` (`ERR_BATCH_NOT_REJECTABLE` otherwise): every item returns to the unbatched pool with `batch_id` null, any computed `settlement_value_cents` is cleared back to null, and the program's `pending_salvage_item_count` is recomputed. A rejected batch never posts money — the settle and reject paths are mutually exclusive in the ledger.

### 3.8. Oversight: Savings Verification, Rebate Attestation, and Compliance Exceptions

Savings verification closes the program's financial loop. A `ProgramManager` creates a report with `program_id`, the `period` under verification in `YYYY-MM` form, a `method` of `ENGINEERING_ESTIMATE` or `METERED_ACTUAL`, the `fiscal_year_label` grouping key such as FY2026, and the OCC field `expected_program_version` per §2.8. Creation is refused when an `ATTESTED` report already exists for the same program and period (`ERR_REPORT_PERIOD_FINALIZED`); a prior `DRAFT` or `REJECTED` report for the same pair is automatically `SUPERSEDED` by the new create. The report is born `DRAFT`, its computed fields fill in at creation, and the program's `version` bumps. The report listing filters by `program_id`, `period`, and `status`.

The kWh computation draws on a burn-hours table per calendar month: January 420, February 380, March 360, April 320, May 290, June 270, July 280, August 310, September 340, October 380, November 410, and December 430. The inclusion set is the program's poles with `led_in_service_date` set and not after the period's last day and with status `CONVERTED`, `REWORK`, `VERIFIED`, or `UNDER_REPAIR` — `EXEMPT` and pre-conversion poles are excluded — and every per-pole quantity is rounded half-up to three decimals before any summation. Under `ENGINEERING_ESTIMATE`, each pole's baseline is its `pre_conversion_wattage` times the month's burn hours divided by 1000, and its actual is its `led_wattage` times burn hours divided by 1000 — the full month credited regardless of the in-service day. Under `METERED_ACTUAL`, the baseline is the same full-month old-fixture figure, while the actual prorates: the old fixture burns the period's days before the in-service date and the LED burns from the in-service date onward — zero LED days when the in-service date falls after the period, the full month when it precedes the period start — with the actual computed as the day-weighted blend, old wattage times burn hours times the pre-in-service day fraction plus LED wattage times burn hours times the remaining day fraction, all divided by 1000. The report's `baseline_kwh` and `actual_kwh` are the sums of the per-pole quantities, `savings_kwh` is their difference rounded half-up to three decimals, and `raw_credit_cents` is `savings_kwh` times the program's `rebate_cents_per_kwh`, rounded half-up.

Submission moves `DRAFT` → `SUBMITTED` (`ERR_REPORT_NOT_DRAFT` otherwise) and requires the books to be closed underneath the period: every tariff account of the program must have `current_period` strictly later than the report's `period`, with no `ESTIMATED` lines remaining in that period (`ERR_REPORT_PERIOD_OPEN`). The submitter is recorded as `submitted_by_user_id`. Attestation and rejection belong to the `Auditor`, require `SUBMITTED` (`ERR_REPORT_NOT_SUBMITTED`), and may not come from the submitting user (`ERR_SEGREGATION_OF_DUTIES`). Attestation computes the capped credit in pinned order: start from `raw_credit_cents`; total the `attested_credit_cents` of the program's other `ATTESTED` reports sharing the same `fiscal_year_label` — `REJECTED`, `SUPERSEDED`, `DRAFT`, and `SUBMITTED` reports contribute nothing, and the report under attestation excludes itself; the remaining headroom is `fy_rebate_cap_cents` minus that total, floored at zero; and `attested_credit_cents` is the smaller of the raw credit and the headroom. The credit posts to `budget_balance_cents` exactly once, `attested_by_user_id` is recorded, and the program's `version` bumps, leaving the report `ATTESTED` and terminal; until attestation, both `attested_credit_cents` and `attested_by_user_id` are null. A rejected report contributes zero to fiscal-year credited totals; revising it requires `REJECTED` (else `ERR_REPORT_NOT_DRAFT`) and returns it to `DRAFT`, clearing `submitted_by_user_id` and recomputing every kWh and credit field from current pole state.

Compliance exceptions carry their own lifecycle of `REQUESTED` → `APPROVED` or `DENIED`, with `EXPIRED` as the time-based terminal state. A `ProgramManager` requests one with `pole_id`, an `exception_kind` of `CCT_WAIVER` or `CONVERSION_EXEMPTION`, `requested_cct_kelvin` — required and greater than zero for a `CCT_WAIVER`, null for a `CONVERSION_EXEMPTION` — and `valid_until`, which must not be before the current date either at request or at approval (`ERR_EXCEPTION_WINDOW_PAST`). Approval and denial belong to the `ComplianceOfficer`, require `REQUESTED` (`ERR_EXCEPTION_NOT_PENDING`), and record `decided_by_user_id`, which is null while the exception remains `REQUESTED`. Approving a `CONVERSION_EXEMPTION` additionally requires the pole to be `AUDIT_CLEARED` (`ERR_POLE_NOT_AUDIT_CLEARED`) and moves it `AUDIT_CLEARED` → `EXEMPT`, excluding it from all future line-generation runs. Expiry is materialized by any authenticated role once the current date has passed `valid_until` (`ERR_EXCEPTION_NOT_EXPIRED` before then), moving `APPROVED` → `EXPIRED`; dispatch-time waiver evaluation does not wait for that materialization and treats a past-`valid_until` approval as expired on its own (§3.4). The exception listing filters by `pole_id`, `exception_kind`, and `status`.

## 4. Endpoint Definitions

All endpoints are mounted under `/streetlights` except the logical-clock operation. Endpoints that create a new resource respond 201; modifications, state transitions, computed operations, and reads respond 200. Request bodies, side effects, and the preconditions behind each transition are specified in §3 — the table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /streetlights/programs | Create a conversion program (`DRAFT`; budget balance initialized to the budget) | ProgramManager |
| GET | /streetlights/programs | List programs; optional `status` filter | All roles |
| GET | /streetlights/programs/{id} | Get one program including computed rollups | All roles |
| GET | /streetlights/programs/{id}/summary | Computed read of budget, billing, salvage, and conversion rollups | All roles |
| POST | /streetlights/programs/{id}/activate | Move the program `DRAFT` → `ACTIVE` | ProgramManager |
| POST | /streetlights/programs/{id}/close | Move the program `ACTIVE` → `CLOSED`; requires all routes terminal | ProgramManager |
| POST | /streetlights/districts | Create a service district with zone-derived dark-sky fields | ProgramManager |
| GET | /streetlights/districts | List districts; filterable by program and zone | All roles |
| GET | /streetlights/districts/{id} | Get one district | All roles |
| POST | /streetlights/poles | Register a pole (`SURVEYED`; effective wattage from nameplate) | ProgramManager |
| GET | /streetlights/poles | List poles; filterable by district, status, ownership | All roles |
| GET | /streetlights/poles/{id} | Get one pole including computed tier and wattages | All roles |
| POST | /streetlights/poles/{id}/attest-nameplate | Utility-owned pole: `SURVEYED` → `AUDIT_CLEARED` without an audit | BillingAnalyst |
| POST | /streetlights/poles/{poleId}/audits | Submit a wattage audit for a municipal pole (OCC version required) | FieldSupervisor |
| GET | /streetlights/audits | List audits; filterable by pole and status | All roles |
| GET | /streetlights/audits/{id} | Get one audit | All roles |
| POST | /streetlights/audits/{id}/accept | `SUBMITTED` → `ACCEPTED`; updates pole wattage; retro billing adjustment | ProgramManager |
| POST | /streetlights/audits/{id}/dispute | `SUBMITTED` → `DISPUTED` | ProgramManager |
| POST | /streetlights/audits/{id}/resubmit | `DISPUTED` → `SUBMITTED` with revised wattage | FieldSupervisor |
| POST | /streetlights/crews | Create a crew | ProgramManager |
| GET | /streetlights/crews | List crews; filterable by program | All roles |
| GET | /streetlights/crews/{id} | Get one crew | All roles |
| POST | /streetlights/conversion-routes | Create a route (`PLANNED`); same-crew closed-window conflict check | ProgramManager |
| GET | /streetlights/conversion-routes | List routes; filterable by district, crew, status | All roles |
| GET | /streetlights/conversion-routes/{id} | Get one route including computed stop and shift fields | All roles |
| POST | /streetlights/conversion-routes/{id}/stops | Add a stop; pole moves to `SCHEDULED`; capacity and duplication checks | ProgramManager |
| GET | /streetlights/route-stops | List stops; filterable; ordered by route then sequence number | All roles |
| GET | /streetlights/route-stops/{id} | Get one stop | All roles |
| POST | /streetlights/route-stops/{id}/skip | `PENDING` stop → `SKIPPED`; linked pending work order cancelled | ProgramManager |
| POST | /streetlights/conversion-routes/{id}/release | `PLANNED` → `RELEASED`; auto-creates one work order per non-skipped stop | ProgramManager |
| POST | /streetlights/conversion-routes/{id}/suspend | `IN_PROGRESS` → `SUSPENDED` (manual) | ProgramManager |
| POST | /streetlights/conversion-routes/{id}/resume | `SUSPENDED` → `IN_PROGRESS`; requires blocked fraction under half | ProgramManager |
| POST | /streetlights/conversion-routes/{id}/cancel | Cancel from `PLANNED`/`RELEASED`/`IN_PROGRESS`/`SUSPENDED` with cascade | ProgramManager |
| GET | /streetlights/work-orders | List work orders; filterable; route-window then sequence ordering | All roles |
| GET | /streetlights/work-orders/{id} | Get one work order (both status dimensions and labor fields) | All roles |
| POST | /streetlights/work-orders/{id}/dispatch | `PENDING`/`REWORK_PENDING` → `DISPATCHED`; fixture spec, safety and fiscal gates, estimate debit | FieldSupervisor |
| POST | /streetlights/work-orders/{id}/complete | `DISPATCHED` → `COMPLETED`; overtime-aware labor; pole, billing, salvage cascade | FieldSupervisor |
| POST | /streetlights/work-orders/{id}/fail | `DISPATCHED` → `FAILED`; system immediately re-queues to `PENDING` | FieldSupervisor |
| POST | /streetlights/work-orders/{id}/cancel | Cancel from `PENDING`/`DISPATCHED`/`REWORK_PENDING` with estimate refund rules | ProgramManager |
| POST | /streetlights/work-orders/{id}/qc-pass | `AWAITING_QC` → `QC_PASSED`; inspector may not be the completer | QaInspector |
| POST | /streetlights/work-orders/{id}/qc-fail | `AWAITING_QC` → `QC_FAILED`; execution → `REWORK_PENDING` | QaInspector |
| POST | /streetlights/rate-schedules | Create a rate schedule (`DRAFT`) | BillingAnalyst |
| GET | /streetlights/rate-schedules | List schedules; filterable by program, ownership class, status | All roles |
| GET | /streetlights/rate-schedules/{id} | Get one schedule | All roles |
| POST | /streetlights/rate-schedules/{id}/file | `DRAFT` → `FILED`; half-open window overlap check | BillingAnalyst |
| POST | /streetlights/rate-schedules/{id}/activate | `FILED` → `EFFECTIVE` | BillingAnalyst |
| POST | /streetlights/rate-schedules/{id}/retire | `EFFECTIVE` → `SUPERSEDED` with shortened window | BillingAnalyst |
| POST | /streetlights/tariff-accounts | Open an unmetered account; period initialized from the clock month | BillingAnalyst |
| GET | /streetlights/tariff-accounts | List accounts; filterable by district, ownership class, status | All roles |
| GET | /streetlights/tariff-accounts/{id} | Get one account including computed totals | All roles |
| POST | /streetlights/tariff-accounts/{id}/freeze | `OPEN` → `FROZEN`; gates line generation and period close | BillingAnalyst |
| POST | /streetlights/tariff-accounts/{id}/unfreeze | `FROZEN` → `OPEN` | BillingAnalyst |
| POST | /streetlights/tariff-accounts/{id}/generate-lines | Create `ESTIMATED` `REGULAR` lines of the current period for eligible poles | BillingAnalyst |
| POST | /streetlights/tariff-accounts/{id}/close-period | `ESTIMATED` lines → `BILLED`; period advances one month | BillingAnalyst |
| GET | /streetlights/billing-lines | List lines; filterable; period-then-creation ordering | All roles |
| GET | /streetlights/billing-lines/{id} | Get one billing line | All roles |
| POST | /streetlights/outage-tickets | Citizen outage report; automatic duplicate linking | CitizenReporter |
| GET | /streetlights/outage-tickets | List tickets; filterable by pole, duplicate link, crew, status, priority | All roles |
| GET | /streetlights/outage-tickets/{id} | Get one ticket | All roles |
| POST | /streetlights/outage-tickets/{id}/triage | `OPEN`/`REOPENED` → `TRIAGED`; computes priority and SLA hours | ProgramManager |
| POST | /streetlights/outage-tickets/{id}/dispatch | `TRIAGED` → `DISPATCHED`; assigns the crew | ProgramManager |
| POST | /streetlights/outage-tickets/{id}/resolve | `DISPATCHED` → `RESOLVED` by assigned crew; breach evaluation and replacement cascade | FieldSupervisor |
| POST | /streetlights/outage-tickets/{id}/verify | `RESOLVED` → `VERIFIED` (reporter only) | CitizenReporter |
| POST | /streetlights/outage-tickets/{id}/reopen | `RESOLVED` → `REOPENED` within 72 hours; priority escalates, SLA clock unchanged | CitizenReporter |
| POST | /streetlights/salvage-batches | Create a salvage batch (`ACCUMULATING`) | ProgramManager |
| GET | /streetlights/salvage-batches | List batches; filterable by program and status | All roles |
| GET | /streetlights/salvage-batches/{id} | Get one batch including computed aggregates | All roles |
| POST | /streetlights/salvage-batches/{id}/items | Move an unbatched salvage item into an `ACCUMULATING` batch, declaring weight and mercury | ProgramManager |
| GET | /streetlights/salvage-items | List salvage items; `batch_id` value `null` selects the unbatched pool | All roles |
| GET | /streetlights/salvage-items/{id} | Get one salvage item | All roles |
| POST | /streetlights/salvage-batches/{id}/seal | `ACCUMULATING` → `SEALED`; records the contamination flag | ComplianceOfficer |
| POST | /streetlights/salvage-batches/{id}/manifest | `SEALED` → `MANIFESTED`; mints the manifest code and computes settlement value | ComplianceOfficer |
| POST | /streetlights/salvage-batches/{id}/settle | `MANIFESTED` → `SETTLED`; credits the program budget | BillingAnalyst |
| POST | /streetlights/salvage-batches/{id}/reject | `SEALED`/`MANIFESTED` → `REJECTED`; items return to the unbatched pool | ComplianceOfficer |
| POST | /streetlights/savings-reports | Create a savings report (OCC version required); supersedes prior draft or rejected report of the period | ProgramManager |
| GET | /streetlights/savings-reports | List reports; filterable by program, period, status | All roles |
| GET | /streetlights/savings-reports/{id} | Get one report | All roles |
| POST | /streetlights/savings-reports/{id}/submit | `DRAFT` → `SUBMITTED`; requires all program accounts past the report period | ProgramManager |
| POST | /streetlights/savings-reports/{id}/attest | `SUBMITTED` → `ATTESTED`; capped rebate credit posts to the budget | Auditor |
| POST | /streetlights/savings-reports/{id}/reject | `SUBMITTED` → `REJECTED`; never the submitter | Auditor |
| POST | /streetlights/savings-reports/{id}/revise | `REJECTED` → `DRAFT`; computed fields refreshed | ProgramManager |
| POST | /streetlights/compliance-exceptions | Request a CCT waiver or conversion exemption for a pole | ProgramManager |
| GET | /streetlights/compliance-exceptions | List exceptions; filterable by pole, kind, status | All roles |
| GET | /streetlights/compliance-exceptions/{id} | Get one exception | All roles |
| POST | /streetlights/compliance-exceptions/{id}/approve | `REQUESTED` → `APPROVED`; conversion exemption requires an audit-cleared pole and exempts it | ComplianceOfficer |
| POST | /streetlights/compliance-exceptions/{id}/deny | `REQUESTED` → `DENIED` | ComplianceOfficer |
| POST | /streetlights/compliance-exceptions/{id}/refresh | Materialize `APPROVED` → `EXPIRED` once past the valid-until date | All roles |
| POST | /_clock/set_current_utc | Set the server's logical clock (default 2026-08-01T00:00:00Z; never wall-clock) | ProgramManager |

## 5. Error Code Catalogue

The catalogue lists every error identifier with its HTTP status. Trigger conditions are specified where the rule lives — §2 for pipeline-wide checks and §3 for workflow-specific ones.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_STALE_VERSION | 412 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_DISTRICT_NOT_FOUND | 404 |
| ERR_POLE_NOT_FOUND | 404 |
| ERR_AUDIT_NOT_FOUND | 404 |
| ERR_CREW_NOT_FOUND | 404 |
| ERR_ROUTE_NOT_FOUND | 404 |
| ERR_STOP_NOT_FOUND | 404 |
| ERR_WORK_ORDER_NOT_FOUND | 404 |
| ERR_RATE_SCHEDULE_NOT_FOUND | 404 |
| ERR_ACCOUNT_NOT_FOUND | 404 |
| ERR_BILLING_LINE_NOT_FOUND | 404 |
| ERR_TICKET_NOT_FOUND | 404 |
| ERR_BATCH_NOT_FOUND | 404 |
| ERR_SALVAGE_ITEM_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_EXCEPTION_NOT_FOUND | 404 |
| ERR_PROGRAM_NOT_ACTIVE | 409 |
| ERR_POLE_NOT_AUDIT_CLEARED | 409 |
| ERR_POLE_EXEMPT | 409 |
| ERR_AUDIT_NOT_SUBMITTED | 409 |
| ERR_ROUTE_NOT_PLANNED | 409 |
| ERR_ROUTE_SUSPENDED | 409 |
| ERR_ROUTE_NOT_SUSPENDED | 409 |
| ERR_ROUTE_STILL_BLOCKED | 409 |
| ERR_ROUTES_STILL_ACTIVE | 409 |
| ERR_STOP_NOT_PENDING | 409 |
| ERR_STOP_BLOCKED | 409 |
| ERR_WORK_ORDER_NOT_DISPATCHABLE | 409 |
| ERR_WORK_ORDER_NOT_COMPLETABLE | 409 |
| ERR_WORK_ORDER_NOT_CANCELLABLE | 409 |
| ERR_QC_NOT_AWAITING | 409 |
| ERR_ACCOUNT_NOT_OPEN | 409 |
| ERR_TICKET_NOT_OPEN | 409 |
| ERR_TICKET_NOT_TRIAGED | 409 |
| ERR_TICKET_NOT_DISPATCHED | 409 |
| ERR_TICKET_NOT_RESOLVED | 409 |
| ERR_BATCH_NOT_ACCUMULATING | 409 |
| ERR_BATCH_NOT_SEALED | 409 |
| ERR_BATCH_NOT_MANIFESTED | 409 |
| ERR_REPORT_NOT_DRAFT | 409 |
| ERR_REPORT_NOT_SUBMITTED | 409 |
| ERR_EXCEPTION_NOT_PENDING | 409 |
| ERR_EXCEPTION_NOT_EXPIRED | 409 |
| ERR_RATE_SCHEDULE_NOT_DRAFT | 409 |
| ERR_RATE_SCHEDULE_NOT_FILED | 409 |
| ERR_RATE_SCHEDULE_NOT_EFFECTIVE | 409 |
| ERR_CCT_EXCEEDS_ZONE_CAP | 422 |
| ERR_SHIELDING_REQUIRED | 422 |
| ERR_ROUTE_WINDOW_OVERLAP | 409 |
| ERR_RATE_WINDOW_OVERLAP | 409 |
| ERR_ROUTE_WINDOW_PAST | 422 |
| ERR_EXCEPTION_WINDOW_PAST | 422 |
| ERR_REOPEN_WINDOW_EXPIRED | 422 |
| ERR_DUPLICATE_POLE_NUMBER | 409 |
| ERR_DUPLICATE_ACCOUNT | 409 |
| ERR_DUPLICATE_SEQUENCE | 409 |
| ERR_DUPLICATE_STOP | 409 |
| ERR_ROUTE_CAPACITY_EXCEEDED | 422 |
| ERR_EMPTY_ROUTE | 422 |
| ERR_ACTIVE_WORK_ORDER_EXISTS | 409 |
| ERR_INSUFFICIENT_WATTAGE_REDUCTION | 422 |
| ERR_AUDIT_ALREADY_PENDING | 409 |
| ERR_EMPTY_BATCH | 422 |
| ERR_UNWEIGHED_ITEMS | 422 |
| ERR_REPORT_PERIOD_FINALIZED | 409 |
| ERR_REPORT_PERIOD_OPEN | 409 |
| ERR_NO_EFFECTIVE_RATE_SCHEDULE | 422 |
| ERR_BATCH_NOT_REJECTABLE | 409 |
| ERR_SALVAGE_ITEM_ALREADY_BATCHED | 409 |
| ERR_CROSS_DISTRICT_STOP | 422 |
| ERR_AUDIT_NOT_PERMITTED_UTILITY | 422 |
| ERR_ATTEST_NOT_PERMITTED_MUNICIPAL | 422 |
| ERR_PROGRAM_BUDGET_EXCEEDED | 402 |
