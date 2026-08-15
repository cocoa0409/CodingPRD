# Aerial Firefighting Contract Operations API — Product Requirements Document

## 1. Introduction

Wildfire agencies such as the USFS and CAL FIRE do not own most of the airtanker fleets they dispatch; they contract them from commercial carriers under two distinct commercial models. Under an **exclusive-use** contract the carrier guarantees that a carded aircraft and crew stand ready every day of the fire season and is paid a daily availability rate for that guarantee, with flight hours billed separately. Under a **call-when-needed** contract the carrier merely offers aircraft on given days, the agency confirms the offers it wants, and the carrier retains the right to decline individual dispatch orders. This document specifies the API that runs those contracts end to end: registering the fleet and crews, certifying readiness through agency carding inspections, posting and confirming daily availability, accepting or declining resource orders, flying and logging sorties against incidents, reloading retardant within a service-level window, and reconciling carrier-submitted invoices against agency flight records before payment.

Two design pressures shape every rule that follows. First, the money is dual-basis: carrier logs produce a provisional bill, but the agency's own flight-time records can replace carrier numbers at reconciliation, so the system keeps both a carrier amount and an agency amount on every flight charge and pins the exact rounding order in which cents are produced. Second, safety limits are hard gates rather than reports: a pilot who reaches eight flight hours in a duty day is automatically pulled off every not-yet-launched assignment, and those releases bubble up into the dispatch order's fill status and, ultimately, into what the carrier may bill. A logical clock governs every deadline, window, and expiry so that an entire contract season is reproducible in test.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The declared roles are `CarrierOps` (carrier operations manager — contracts, fleet, crew, availability, dispatch acceptance, assignments, retardant loading, rest releases), `AgencyDispatcher` (agency dispatch — incidents, resource orders, availability confirmation, assignment release), `Pilot` (pilot in command — acts only on their own assignments), `CarrierFinance` (carrier billing — creates, submits, resubmits, and voids invoices, but never reconciles them), `AgencyFinance` (agency payment office — imports agency records, and disputes, reconciles, and marks invoices paid), `CardingInspector` (agency inspector — schedules, completes, and reschedules readiness inspections for aircraft and crew), and `SystemAdmin` (a test-driving operator used only for the logical clock). A request with a missing header, or a role that is not one of these declared values, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but does not appear on the endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Identity works differently for exactly one role. When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of the acting `CrewMember`; ownership checks on any resource that references a crew member compare the resource's foreign-key field — most importantly an assignment's `pilot_id` — to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is any of `CarrierOps`, `AgencyDispatcher`, `CarrierFinance`, `AgencyFinance`, `CardingInspector`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `submitted_by` or `reconciled_by` on an invoice) but does not compare it to any entity's `id`. One segregation-of-duties rule does compare opaque identifiers: the operator who reconciles an invoice must not be the operator who submitted it, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Most list endpoints also accept exact-match filters named after the resource's own fields. The contract list filters by `status` and `contract_type`; the aircraft list by `contract_id` and `carding_status`; the crew list by `contract_id`, `duty_status`, and `carding_status`; the availability list by `aircraft_id`, `contract_id`, `service_date`, and `status`; the incident list by `status` and `agency`; the dispatch-order list by `contract_id`, `incident_id`, and `status`; the assignment list by `aircraft_id`, `pilot_id`, `dispatch_order_id`, and `status`; and the invoice line-item list by `line_type`. Reverse-reachability lists under a parent resource accept their own date- or status-scoped filters: a contract's availability periods filter by `service_date` and `status`, its invoices by `status`, and its agency records by `record_date`; an aircraft's or a crew member's inspections filter by `result`; a crew member's duty days filter by `duty_date` and flight logs by `logged_date`; and a dispatch order's assignments filter by `status`.

### 2.4. Common Resource Properties

Every primary resource carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits captured at creation; `updated_at`, refreshed on every mutation; and `version`, an integer that increments by exactly 1 on every mutation of that resource — including mutations caused by cascades rather than by direct client calls. Three ledger-style resources are the exception: a FlightLog, an InvoiceLineItem, and an AgencyRecord carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because these records are append-only and are never mutated after creation.

### 2.5. Nested Resource Retrieval and Reference Validation

When an endpoint path contains more than one identifier — for example, creating an assignment under a dispatch order, or a flight log under an assignment — identifiers are validated strictly left to right: path identifiers first, in path order, then body identifiers in declaration order. The request is rejected with the not-found variant for the first reference that does not exist, and no later check runs. Each resource has its own not-found error, all HTTP 404: `ERR_CONTRACT_NOT_FOUND`, `ERR_AIRCRAFT_NOT_FOUND`, `ERR_CREW_MEMBER_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_DISPATCH_ORDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_AVAILABILITY_PERIOD_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, and `ERR_RETARDANT_LOAD_NOT_FOUND`.

### 2.6. Money, Tenths of an Hour, and Rounding

All monetary amounts are integer cents — rates, daily charges, subtotals, penalties, and season totals alike — and every rounding applied to money is round half up to a whole cent. Flight time is tracked in tenths of an hour as integers; conversions from raw Hobbs hours or planned windows to tenths round half up to a whole tenth. Where an average is exposed, as with the reload turn average, it rounds half up to one decimal place. Dates use the `YYYY-MM-DD` form and instants use ISO 8601 UTC. No calculation anywhere in the system uses banker's rounding, truncation, or unrounded floating-point arithmetic; where two orderings of a computation would yield different cents, the pinned ordering given in §3 is the only sanctioned one.

### 2.7. The Logical Clock

The server runs on a logical clock rather than wall-clock time. Before any explicit set, the clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `SystemAdmin`-only test-driving capability advances the clock to a supplied instant given in the `to_iso8601` request field; the response carries the new value as `current_utc`. Every system-stamped instant — `placed_at`, `assigned_at`, `launched_at`, `arrived_at`, `released_at`, `demobilized_at`, `submitted_at` — reads this clock, as do all deadline, expiry, and window evaluations: acceptance windows, confirm windows, carding expiry, billing-period closure, and rest-release eligibility. Setting the clock mutates no entity.

### 2.8. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, each anchored on the parent resource in its path.

Creating an invoice under a contract requires the request to carry `expected_contract_version`, the contract `version` the client last observed. If another accepted write — an invoice creation, an availability cascade, a submit or void adjustment — has advanced the contract's version since that read, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from billing against a contract view it has not observed.

Creating an assignment under a dispatch order requires `expected_dispatch_order_version`, the order `version` the client last observed. Because accepted assignment creations and release cascades advance the order's version, a create carrying a previously observed version is stale and is likewise refused with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; optimistic checks exist only on these two creation paths.

### 2.9. Validation Order and Error Precedence

When several rules would reject the same request, the system does not choose arbitrarily: checks run in a fixed priority order, and the earliest failing check produces the response.

1. **Authentication** — headers present and role declared (`ERR_UNAUTHENTICATED`).
2. **Role authorization** — the acting role appears in the endpoint's role list (`ERR_UNAUTHORIZED_ROLE`).
3. **Request shape** — required fields present, types valid, enum members valid, date and datetime formats valid, and the intrinsic orderings: `hobbs_stop` strictly after `hobbs_start`, `available_end` strictly after `available_start`, `planned_end` strictly after `planned_start`, `period_end` on or after `period_start`, `season_end_date` strictly after `season_start_date`, and exactly one of an inspection's two subjects set. Any violation is `ERR_INVALID_REQUEST` (HTTP 400).
4. **Reference existence** — path then body, left to right (the per-resource 404s of §2.5).
5. **Ownership and segregation of duties** — pilot self-assignment checks and the invoice submitter/reconciler split (`ERR_FORBIDDEN_OWNERSHIP`, `ERR_SEGREGATION_OF_DUTIES`).
6. **Optimistic concurrency** — the two version fields of §2.8 (`ERR_STALE_VERSION`).
7. **State-machine legality** — the requested transition must be valid from the entity's current state (`ERR_INVALID_STATE`, HTTP 409); terminal states reject every further action (`ERR_ALREADY_TERMINAL`, HTTP 409) — terminal means a `CLOSED` contract, incident, or dispatch order, a `DECLINED` or `CANCELLED` order, a `DECARDED` aircraft, a `PAID` or `VOID` invoice, a `DEMOBILIZED` assignment, a `DROPPED` load, and an `EXCUSED` or `UNAVAILABLE` availability period; a contract must be `ACTIVE` to accept new business (`ERR_CONTRACT_NOT_ACTIVE`, HTTP 409); aircraft and pilot must be `CARDED` at assignment creation (`ERR_AIRCRAFT_NOT_CARDED`, `ERR_CREW_NOT_CARDED`); and an order already holding its requested quantity of live assignments refuses more (`ERR_DISPATCH_ALREADY_FILLED`).
8. **Flight safety** — carding validity at launch (`ERR_CARDING_EXPIRED`), fatigue hold (`ERR_CREW_ON_FATIGUE_HOLD`), the daily flight-hour limit (`ERR_FLIGHT_HOUR_LIMIT_EXCEEDED`), and the duty-day span limit (`ERR_CREW_DAY_LIMIT_EXCEEDED`).
9. **Overlap, uniqueness, and capacity** — assignment window overlap (`ERR_ASSIGNMENT_OVERLAP`), one availability period per aircraft and date (`ERR_AVAILABILITY_OVERLAP`), one non-`VOID` invoice per contract and period start (`ERR_INVOICE_PERIOD_OVERLAP`), and tank capacity (`ERR_TANK_CAPACITY_EXCEEDED`).
10. **Crew rest buffer** — the sixty-minute gap rule (`ERR_DUTY_REST_VIOLATION`).
11. **Linkage and qualification** — aircraft and pilot belonging to the order's contract (`ERR_AIRCRAFT_NOT_ON_CONTRACT`, `ERR_PILOT_NOT_ON_CONTRACT`), the required-model check (`ERR_MODEL_MISMATCH`), and model qualification (`ERR_MODEL_NOT_QUALIFIED`).
12. **Temporal windows** — acceptance deadline (`ERR_ACCEPTANCE_WINDOW_EXPIRED`), confirm window (`ERR_CONFIRM_WINDOW_EXPIRED`), season bounds (`ERR_SERVICE_DATE_OUTSIDE_SEASON`), and billing-period closure (`ERR_BILLING_PERIOD_NOT_CLOSED`).
13. **Season flight-hour cap** (`ERR_SEASON_FLIGHT_CAP_EXCEEDED`).

The precedence bites in practice: an assignment creation that would both overlap another of the aircraft's commitments and push the pilot's projection over the daily limit is rejected with the flight-hour error, because safety (step 8) outranks overlap (step 9); and a request whose version field is stale fails at step 6, before any of those business checks are consulted at all.

### 2.10. Season Ledgers, Derived Order Status, and Cross-Entity Cascades

Two running totals live on every contract. `season_billed_cents` tracks what the carrier has actually put into the billing pipeline, and `season_flight_hours_tenths` tracks every sortie hour charged against the season cap. Both are maintained invariantly — the exact membership rules live in §3.6 and §3.8 — and every adjustment to either is a mutation of the contract: `updated_at` refreshes and `version` increments. Derived state behaves the same way elsewhere: a dispatch order's fill band is never set by clients but is computed from the live states of its child assignments, bubbling up whenever an assignment is created, released, or demobilized. Cascades in this domain are deliberate and multi-link — a failed inspection can suspend an aircraft, flip its confirmed availability days, and rewrite draft invoices in one sweep; a single flight log can push a pilot onto fatigue hold, release pending assignments, and shift orders back down the fill band. Every entity touched by such a cascade — period, invoice, crew member, assignment, order, contract — takes its own version increment.

## 3. Business Logic & Workflows

### 3.1. Contract Onboarding and the Season Lifecycle

A `CarrierOps` operator opens a new contract by supplying the carrier-assigned `contract_number`, unique across all contracts, the contracting `agency` (`USFS` or `CAL_FIRE`), and the `contract_type` — `EXCLUSIVE_USE` for a guaranteed-availability arrangement with a mandatory dispatch-acceptance window, or `CALL_WHEN_NEEDED` for an arrangement where the agency must confirm offered availability and the carrier may decline individual orders. Commercial terms arrive as `daily_availability_rate_cents` and `flight_hour_rate_cents`, both strictly positive integer cents. The season is delimited by `season_start_date` and `season_end_date`, the end strictly after the start. `min_daily_available_minutes` sets the available-minutes threshold an exclusive-use day must reach to bill at full rate; when omitted it defaults to 570 minutes — nine and a half hours of daily standby — and must be strictly positive when supplied. `season_flight_hour_cap_tenths` caps total season flying in tenths of an hour, so a 200.0-hour cap is registered as 2000, and `acceptance_window_minutes` fixes how many minutes the carrier has to accept each dispatch order; both are strictly positive. A new contract is born in `DRAFT` with `season_billed_cents` and `season_flight_hours_tenths` both zero.

Activation moves the contract from `DRAFT` to `ACTIVE`. Only an `ACTIVE` contract accepts new business: placing a resource order, posting an availability period, or creating an invoice against a contract in any other state is refused with `ERR_CONTRACT_NOT_ACTIVE`. A stop-work order suspends the contract (`ACTIVE` → `SUSPENDED`); suspension gates new business only and deliberately leaves in-flight assignments and `DRAFT` invoices untouched, and a later resume (`SUSPENDED` → `ACTIVE`) lifts it — the `ACTIVE` → `SUSPENDED` → `ACTIVE` cycle exists precisely so that stop-work orders can be raised and lifted mid-season. Closing is allowed from either `ACTIVE` or `SUSPENDED`, but only once no dispatch order of the contract remains in `PLACED`, `ACCEPTED`, `PARTIALLY_FILLED`, or `FILLED`. `CLOSED` is terminal: any further action on a closed contract is rejected with `ERR_ALREADY_TERMINAL`. Each lifecycle transition increments the contract's `version`.

### 3.2. Fleet, Crew, and the Carding Program

Aircraft join a contract by registration: a unique FAA `tail_number`, a `model` code such as AT-802F, a strictly positive `tank_capacity_gallons`, and the `contract_id` of the contract they are listed on. New aircraft are `UNCARDED` with a null `carded_until`. Crew members are registered with a `full_name`, a `crew_role` of `PIC` or `SIC`, their employing `contract_id`, and `qualified_aircraft_models` — an array of model codes where an empty array means qualified on none. A crew member carries two independent status dimensions that evolve in parallel: `carding_status` (`UNCARDED`, `CARDED`, or `SUSPENDED` — people are never decarded), beginning at `UNCARDED` with null `carded_until`; and `duty_status` (`AVAILABLE` or `FATIGUE_HOLD`), beginning at `AVAILABLE`.

Readiness is certified through carding inspections. A `CardingInspector` schedules one for exactly one subject — `subject_aircraft_id` or `subject_crew_member_id`; a request naming both or neither is rejected as `ERR_INVALID_REQUEST`. The inspection records `scheduled_for`, an optional `valid_days` that defaults to 365 and must be strictly positive when supplied, and optional `notes`. It is born `SCHEDULED` with `result` `PENDING` and `completed_at` null. Completion moves the inspection `SCHEDULED` → `COMPLETED` and supplies a `result` of `PASSED` or `FAILED` together with `completed_at`; completing an inspection that is not `SCHEDULED`, or one whose `completed_at` precedes its `scheduled_for`, is rejected with `ERR_INVALID_STATE`. On `PASSED`, the subject — aircraft or crew member — becomes `CARDED`, with `carded_until` set to the calendar date of `completed_at` plus `valid_days` days; this holds whether the subject was `UNCARDED` or previously `SUSPENDED`. On `FAILED`, a `CARDED` subject drops to `SUSPENDED` and its `carded_until` is cleared.

An aircraft failure does not stop there. Every availability period of that aircraft still in `CONFIRMED` whose `service_date` falls on or after the failure's calendar date flips to `UNAVAILABLE` with `excuse_reason` set to `CARDING`, its charge zeroed and its own version bumped. Each such flip in turn re-derives every `DRAFT` invoice of the same contract whose billing period covers the affected `service_date`: line items are regenerated, the totals of §3.8 recomputed, and each invoice's version bumped. The aircraft's own version increments as well — three links in one cascade, from inspection to aircraft to availability to invoices. A failed crew inspection fires no availability cascade; it merely suspends the person. Nor does a later pass repair old damage: periods already flipped to `UNAVAILABLE` stay `UNAVAILABLE`, because that state is terminal and the compensation is explicit — the carrier posts nothing and the day simply never bills. When a `COMPLETED` inspection ended in failure, the inspector may reschedule it, moving it `COMPLETED` → `SCHEDULED` with `result` reset to `PENDING`, `completed_at` cleared, and a new `scheduled_for`; this `COMPLETED`(failed) → `SCHEDULED` → `COMPLETED` loop is the reinspection revision path.

An aircraft leaves service through decarding. From `CARDED`, decarding is blocked while any of its assignments remains in `ASSIGNED`, `EN_ROUTE`, or `ON_INCIDENT`; from `UNCARDED` it may be decarded directly. Either path clears `carded_until` and lands in `DECARDED`, which is terminal.

### 3.3. Posting Availability and the Daily Availability Charge

Day-by-day availability is the carrier's side of the bargain. A `CarrierOps` operator offers an aircraft on a `service_date` by naming the `aircraft_id` and the window `available_start` to `available_end`, the end strictly after the start. The service date must lie inside the contract's season, from `season_start_date` through `season_end_date` inclusive, or the offer is rejected with `ERR_SERVICE_DATE_OUTSIDE_SEASON`; the contract itself must be `ACTIVE`; and at most one availability period may ever exist per aircraft per date — a second period for the same pair, in any status, is `ERR_AVAILABILITY_OVERLAP`. From the window the system derives `available_minutes`, its whole-minute length. The period's initial status depends on the contract type: `CONFIRMED` at birth under an `EXCLUSIVE_USE` contract, but merely `OFFERED` under `CALL_WHEN_NEEDED`, awaiting agency confirmation.

The daily availability charge follows the contract model. A day in `EXCUSED` or `UNAVAILABLE` never bills. Under a call-when-needed contract, a `CONFIRMED` day bills the flat `daily_availability_rate_cents` regardless of minutes, while an `OFFERED` day bills nothing. Under an exclusive-use contract, a `CONFIRMED` day whose `available_minutes` reaches `min_daily_available_minutes` bills the full daily rate — the threshold is inclusive — while a shorter day bills a linear prorate: the daily rate multiplied by the ratio of `available_minutes` to `min_daily_available_minutes`, rounded half up to a whole cent. The charge is computed when the period is created and recomputed on confirm, on excuse, on a carding-cascade flip, and whenever a covering draft invoice is re-derived; it is stored on the period as `availability_charge_cents`.

An `AgencyDispatcher` confirms an offered day, moving it `OFFERED` → `CONFIRMED`, but only while the clock's date is on or before the `service_date`; confirming after the day has passed is `ERR_CONFIRM_WINDOW_EXPIRED`. Confirmation recomputes the charge and re-derives any covering draft invoices. A `CarrierOps` operator may instead excuse a day from either `OFFERED` or `CONFIRMED`, supplying an `excuse_reason` of `MAINTENANCE`, `CARDING`, `WEATHER`, or `AGENCY_RELEASE`; excusing zeroes the charge, and excusing a `CONFIRMED` day additionally re-derives covering draft invoices. Both `EXCUSED` and `UNAVAILABLE` are terminal for a period.

### 3.4. Incidents and Resource Ordering

An incident begins when an `AgencyDispatcher` reports it with a unique agency `incident_number`, a `name`, a free-form `location`, the owning `agency`, and a `priority` of `INITIAL_ATTACK` or `EXTENDED_ATTACK`. Incidents advance strictly along `REPORTED` → `ACTIVE` → `CONTAINED` → `CLOSED`, each step taken by naming the target in `to_status`; `CLOSED` is terminal.

Against an `ACTIVE` contract, a dispatcher places a resource order: a unique `order_number`, the `contract_id` and `incident_id` the order draws on, the strictly positive `aircraft_quantity` requested, and an optional `required_model`. Placement is gated by the season flight-hour cap — the contract's `season_flight_hours_tenths` must still be below `season_flight_hour_cap_tenths`, otherwise the order is refused with `ERR_SEASON_FLIGHT_CAP_EXCEEDED`. The order records `placed_at` from the logical clock, computes `accept_deadline` as `placed_at` plus the contract's `acceptance_window_minutes`, and is born `PLACED` with `filled_count` zero and `decline_reason` null.

The carrier answers inside the window. Acceptance — `PLACED` → `ACCEPTED` by `CarrierOps` — requires the contract still `ACTIVE` and the clock at or before `accept_deadline`; exactly at the deadline is allowed, while a later acceptance is `ERR_ACCEPTANCE_WINDOW_EXPIRED`. Declining a `PLACED` order captures the carrier's `decline_reason` and lands in `DECLINED`. The agency may cancel an order from `PLACED`, or from `ACCEPTED` so long as `filled_count` is still zero. `DECLINED`, `CANCELLED`, and `CLOSED` are all terminal.

From acceptance onward the order's fill band is a derived aggregate of its assignments, never set directly. `filled_count` always equals the number of the order's assignments currently in `ASSIGNED`, `EN_ROUTE`, or `ON_INCIDENT`. Creating an assignment that leaves the count short of `aircraft_quantity` moves the band to `PARTIALLY_FILLED`; reaching exactly the requested quantity moves it to `FILLED`, from either `ACCEPTED` or `PARTIALLY_FILLED`; a release that drops a `FILLED` order back below quantity returns it to `PARTIALLY_FILLED`; and a release that empties a partially filled order returns it to `ACCEPTED`. The band therefore behaves like a compensating pair around any create-then-release sequence: count and derived status end exactly where they began. When a demobilization leaves every assignment of an order in `DEMOBILIZED` — and at least one assignment exists — the order closes itself from whichever of `ACCEPTED`, `PARTIALLY_FILLED`, or `FILLED` it occupies. Each bubble-up increments the order's version.

### 3.5. Filling an Order: The Assignment Gate Chain

To fill an accepted order, a `CarrierOps` operator creates an assignment naming the `aircraft_id`, the `pilot_id` of the pilot in command, and the planned window `planned_start` to `planned_end` — end strictly after start — while carrying `expected_dispatch_order_version` per §2.8. The new assignment is born `ASSIGNED`, its `assigned_at` stamped from the clock, its `launched_at`, `arrived_at`, `released_at`, and `demobilized_at` all null, its `release_reason` unset, and its reload fields `reload_turn_avg_minutes` null and `reload_sla_breach` false until loads are turned.

Creation runs the full gate chain in the priority order of §2.9 — state, then safety, then overlap, then rest, then linkage — and the first failing gate decides the response.

- **State gates.** The order must be non-terminal and not yet full: when `filled_count` already equals `aircraft_quantity`, creation is refused with `ERR_DISPATCH_ALREADY_FILLED`. Both the aircraft and the pilot must currently be `CARDED`, or creation fails with `ERR_AIRCRAFT_NOT_CARDED` or `ERR_CREW_NOT_CARDED` respectively.
- **Safety gates.** A pilot on `FATIGUE_HOLD` may not be assigned at all (`ERR_CREW_ON_FATIGUE_HOLD`). The forward-looking flight-hour projection for the pilot's duty day — `projected_tenths` on the `CrewDutyDay` keyed by `crew_member_id` and `duty_date` — must remain at or below 80 tenths, eight flight hours, *including* the candidate assignment's own planned window: a projection of 81 or more is `ERR_FLIGHT_HOUR_LIMIT_EXCEEDED`, while exactly 80 passes. The projection adds to the day's recorded `flown_tenths` the planned windows — converted to tenths with round-half-up — of every one of the pilot's assignments still in `ASSIGNED` whose `planned_start` falls on that duty date, so the two variants legitimately disagree: with 75 flown tenths and one assigned 1.0-hour window, the projection reads 85 while actuals remain 75. Independently, the duty-day span — the candidate's `planned_end` minus the duty day's `duty_start` — must not exceed 840 minutes, fourteen hours; exactly 840 is allowed and anything beyond is `ERR_CREW_DAY_LIMIT_EXCEEDED`.
- **Overlap gate.** The aircraft's planned window is compared half-openly against every non-terminal assignment of the same aircraft — any assignment that has not reached `DEMOBILIZED`. Overlapping windows are `ERR_ASSIGNMENT_OVERLAP`; back-to-back windows that merely touch are allowed.
- **Rest gate.** The pilot must carry a sixty-minute buffer around the new window in both directions: every non-terminal assignment window of the pilot must end at least sixty minutes before the candidate's `planned_start`, or begin at least sixty minutes after its `planned_end`. Mere adjacency is not rest, and a violation is `ERR_DUTY_REST_VIOLATION`.
- **Linkage and qualification gates.** The aircraft and the pilot must both belong to the order's contract (`ERR_AIRCRAFT_NOT_ON_CONTRACT`, `ERR_PILOT_NOT_ON_CONTRACT`); when the order names a `required_model`, the aircraft's `model` must equal it (`ERR_MODEL_MISMATCH`); and the aircraft's model must appear in the pilot's `qualified_aircraft_models` (`ERR_MODEL_NOT_QUALIFIED`).

A successful creation ripples outward. If no `CrewDutyDay` exists yet for the pilot on the calendar date of `planned_start`, one is created with `duty_start` set to that `planned_start` — at most one duty day ever exists per `crew_member_id` and `duty_date` pair — and its `projected_tenths` is recomputed. The order's `filled_count` recomputes per the invariant of §3.4, possibly walking the band to `PARTIALLY_FILLED` or `FILLED`, and the order's version increments.

### 3.6. Flying the Assignment: Sorties, Fatigue, and Demobilization

Launch moves an assignment `ASSIGNED` → `EN_ROUTE` and may be performed by `CarrierOps` or by the assigned pilot personally; a `Pilot` caller whose `X-User-ID` does not equal the assignment's `pilot_id` is rejected with `ERR_FORBIDDEN_OWNERSHIP`. Launch re-verifies readiness at the moment of departure: the aircraft must be `CARDED` with `carded_until` on or after the current clock date — an expired card is `ERR_CARDING_EXPIRED` — and the pilot must not be on `FATIGUE_HOLD` (`ERR_CREW_ON_FATIGUE_HOLD`). A successful launch stamps `launched_at`. Arrival then moves the assignment `EN_ROUTE` → `ON_INCIDENT` under the same pilot-ownership rule, stamping `arrived_at`; only an on-incident assignment may log flight time or take on retardant.

Flight logs are the pilot's own record: only a `Pilot` may append one, only to their own assignment, and only while that assignment is `ON_INCIDENT` — logging against an assignment in any other state is `ERR_INVALID_STATE`. Each log names its `assignment_id` through the path it is filed under and carries the `logged_date` the flight is charged to plus the Hobbs meter readings `hobbs_start` and `hobbs_stop`, the stop strictly greater than the start. Rounding order is pinned per sortie, and the pin matters: first the sortie's duration becomes `flight_hours_tenths` by rounding the hour difference times ten half up to a whole tenth; then `billable_cents` is computed from those tenths at the contract's `flight_hour_rate_cents`, again rounded half up to a whole cent. Summing raw hours first and rounding once is forbidden, because it produces different money — two sorties of 1.05 and 0.65 hours at 300,000 cents per hour bill 330,000 plus 210,000, that is 540,000 cents, per-sortie, against 510,000 under sum-first. The log's `pilot_id` is copied from the assignment at creation and cannot diverge from it.

Every logged sortie runs two accumulating gates before acceptance. The chronological flight-hour gate sums the pilot's `flight_hours_tenths` over that `logged_date` — creating the `CrewDutyDay` on the fly if none exists, in which case its `duty_start` stays null — and refuses the log with `ERR_FLIGHT_HOUR_LIMIT_EXCEEDED` when the day total including the new sortie would exceed 80 tenths; exactly 80 is accepted. The season gate refuses the log with `ERR_SEASON_FLIGHT_CAP_EXCEEDED` when the contract's `season_flight_hours_tenths` plus the new tenths would exceed `season_flight_hour_cap_tenths`. An accepted sortie adds its tenths to the contract's season total — bumping the contract's version — refreshes the duty day's `flown_tenths` and `projected_tenths`, and triggers re-derivation of any draft invoices whose billing period covers the `logged_date`.

Reaching the daily limit has teeth: the moment a log raises a duty day's `flown_tenths` to 80 or more, a four-link cascade fires. The duty day absorbs the new tenths; the crew member's `duty_status` flips to `FATIGUE_HOLD` with a version bump; every assignment of that pilot still in `ASSIGNED` flips to `RELEASED` with `release_reason` `FATIGUE` and `released_at` stamped from the clock — assignments already `EN_ROUTE` or `ON_INCIDENT` are deliberately left flying; and each released assignment's order recomputes its fill band, stepping `FILLED` down to `PARTIALLY_FILLED`, or a zeroed `PARTIALLY_FILLED` back to `ACCEPTED`, bumping order versions as it goes. A pilot returns from hold only through a `CarrierOps` rest release, and only once their latest duty day's `duty_date` is strictly before the current clock date — rest is measured in whole calendar days.

An agency dispatcher may release an assignment from `ASSIGNED`, `EN_ROUTE`, or `ON_INCIDENT`, supplying a `release_reason` of `AGENCY` or `MECHANICAL`; the release stamps `released_at`, recomputes the order's fill band, and refreshes the affected duty day's `projected_tenths`. Finally, `CarrierOps` demobilizes a `RELEASED` assignment, stamping `demobilized_at`; when that demobilization leaves every assignment of the order in `DEMOBILIZED` — with at least one assignment existing — the order closes itself. `DEMOBILIZED` is the assignment's terminal state.

### 3.7. Retardant Reloads and the Turn-Time SLA

While an assignment is `ON_INCIDENT`, `CarrierOps` may request a retardant load of `gallons` — strictly positive and never more than the aircraft's `tank_capacity_gallons`, or the request is refused with `ERR_TANK_CAPACITY_EXCEEDED`. The request stamps `requested_at` from the logical clock unless the caller supplies it explicitly, and the load is born `REQUESTED`. Completing the load moves it to `LOADED` with a supplied `loaded_at` that must not precede `requested_at`, and dropping it over the fire moves it `LOADED` → `DROPPED` with a supplied `dropped_at` that must not precede `loaded_at`; violating either ordering, or acting out of state, is `ERR_INVALID_STATE`. The drop may be called by `CarrierOps` or by the assignment's own pilot under the same ownership rule as launch. `DROPPED` is terminal.

Each load's turnaround is measured against the assignment's previous drop: `reload_turn_minutes` is the whole-minute difference between the load's `loaded_at` and the most recent earlier drop among the same assignment's loads — the previous load being the one with the greatest `dropped_at` strictly before this `loaded_at`, ties on equal `dropped_at` broken by earlier `created_at`, never by `id`. The first load of an assignment has no predecessor, so its `reload_turn_minutes` stays null. Every load completion recomputes the assignment's `reload_turn_avg_minutes` — the mean of its non-null turn times, rounded half up to one decimal place, null while no turns exist — and re-derives `reload_sla_breach`, which is true only when that average is strictly greater than 30.0 minutes; an average of exactly 30.0 is not a breach. Both the load's and the assignment's versions increment on load completion.

### 3.8. Invoicing, Reconciliation, and Payment

Billing begins when a `CarrierFinance` operator creates an invoice under an `ACTIVE` contract, naming `period_start` and `period_end` — the end on or after the start — and carrying `expected_contract_version` per §2.8; the creation itself bumps the contract's version. At most one non-`VOID` invoice may exist per contract and `period_start` pair; a repeat period start is `ERR_INVOICE_PERIOD_OVERLAP`. A new invoice is `DRAFT` on the `PROVISIONAL` billing basis — carrier logs — with `availability_subtotal_cents`, `flight_subtotal_cents`, `penalty_cents`, and `net_cents` all zero, and `submitted_by`, `submitted_at`, `reconciled_by`, and `dispute_reason` all null.

Line generation is deterministic. The input set is the contract's availability periods with `service_date` inside the billing period and status in `CONFIRMED`, `UNAVAILABLE`, or `EXCUSED` — `OFFERED` days never bill — together with the flight logs of assignments whose dispatch order traces back to this contract and whose `logged_date` falls inside the period. Each invoice line item records its owning `invoice_id`, a `line_type` of `AVAILABILITY_DAY`, `FLIGHT_DAY`, or `PENALTY`, a `reference_date` — the availability day's `service_date`, the flight day's `logged_date`, or the period date for a penalty — and a `source_ref_id` naming the availability period, the assignment, or the invoice itself respectively. Availability lines carry `carrier_qty` equal to the day's `available_minutes` and `carrier_amount_cents` equal to the day's `availability_charge_cents`; availability bills on the carrier basis under both variants, always. Flight lines aggregate per assignment per `logged_date`: `carrier_qty` sums the day's per-sortie `flight_hours_tenths` and `carrier_amount_cents` sums the per-sortie `billable_cents`. A penalty line carries `carrier_qty` zero and `carrier_amount_cents` equal to the negated `penalty_cents`. Every line also carries `agency_qty`, null until reconciliation or when no agency record matches, `agency_amount_cents`, a `billed_amount_cents` equal to the carrier amount while the invoice is `PROVISIONAL` and to the agency amount once `RECONCILED`, and a `mismatch_flag` defaulting to false. Lines are emitted in a pinned order: availability days by `service_date` ascending, then flight days by `reference_date` ascending with ties broken by the assignment's `created_at` ascending, then the penalty line last.

The invoice totals compose in a pinned six-step sequence, and the sequence is part of the contract. First, `availability_subtotal_cents` sums the carrier amounts of the availability lines. Second, `flight_subtotal_cents` sums `billed_amount_cents` over the flight lines under the current basis. Third, the expected day count is the number of availability lines. Fourth, the compliant day count adds availability lines whose period was `CONFIRMED` with `available_minutes` at least `min_daily_available_minutes`, plus lines whose period is `EXCUSED`. Fifth, `penalty_cents` is five percent of `availability_subtotal_cents`, rounded half up to whole cents — but only when at least one availability day exists and the ratio of compliant to expected days falls below 0.98, compared as an exact rational: compliant days times one hundred strictly less than expected days times ninety-eight. With no availability days at all, the penalty is zero. Sixth, `net_cents` is the availability subtotal plus the flight subtotal minus the penalty. Evaluating the net before the penalty, or keying the ratio on the net, is forbidden. A `DRAFT` invoice is live: any source mutation — an availability confirm, excuse, or cascade flip, or a new in-period flight log — regenerates its lines and recomputes these totals, bumping the invoice's version. Once an invoice leaves `DRAFT`, its numbers freeze, with the single exception of a clean reconciliation's agency-basis recompute.

Submission moves the invoice `DRAFT` → `SUBMITTED` and is allowed only once the billing period has fully closed — `period_end` strictly before the current clock date, otherwise `ERR_BILLING_PERIOD_NOT_CLOSED`. Submitting stamps `submitted_by` with the operator's `X-User-ID` and `submitted_at` with the clock, and debits the contract: `season_billed_cents` increases by the invoice's `net_cents`, bumping the contract version alongside the invoice's. That ledger obeys a standing invariant — it always equals the sum of `net_cents` over the contract's invoices in `SUBMITTED`, `DISPUTED`, `RECONCILED`, or `PAID` — so a submission followed later by a void of the same invoice leaves the ledger exactly at its pre-submit value.

Dispute and negotiation form a deliberate cycle. An `AgencyFinance` operator may dispute a `SUBMITTED` invoice, recording a `dispute_reason`; the invoice stays on the `PROVISIONAL` basis and the season ledger does not move, because `DISPUTED` remains inside the invariant set. `CarrierFinance` may then resubmit, clearing `dispute_reason` and restamping `submitted_by` and `submitted_at`, again without ledger movement — the `SUBMITTED` → `DISPUTED` → `SUBMITTED` loop is the carrier/agency negotiation path.

Reconciliation is where the two ledgers meet. An `AgencyFinance` operator reconciles a `SUBMITTED` invoice — but never the same operator who submitted it, a separation enforced with `ERR_SEGREGATION_OF_DUTIES`. Agency flight-time records are imported ahead of time by `AgencyFinance`, each naming its `contract_id`, `assignment_id`, `record_date`, and `agency_flight_hours_tenths` (zero or more tenths), with optional `agency_available_minutes` that are informational only, since availability always bills carrier-basis. For each flight line, the reconcile finds the agency record whose `assignment_id` equals the line's `source_ref_id` and whose `record_date` equals the line's `reference_date`. On a match, `agency_qty` takes the record's `agency_flight_hours_tenths`, `agency_amount_cents` is computed from those tenths at the contract's flight-hour rate with round-half-up to whole cents, and `mismatch_flag` is set when carrier and agency quantities differ by more than one tenth of an hour — a difference of exactly one tenth is within tolerance. Without a match, the line's agency fields simply mirror the carrier values and no mismatch is flagged; availability and penalty lines always mirror the carrier amount and never mismatch. If any flight line mismatches, the invoice drops to `DISPUTED` with `dispute_reason` set to `RECONCILIATION_MISMATCH`, basis unchanged, net unchanged. Otherwise the invoice moves to `RECONCILED`: `billing_basis` becomes `RECONCILED`, `reconciled_by` records the operator, every flight line's `billed_amount_cents` switches to its agency amount, the flight subtotal and net recompute under the pinned sequence, the season ledger shifts by the difference between new and old net, and both the invoice's and the contract's versions increment. Identical carrier data can therefore legitimately bill differently across bases: 50 carrier tenths versus 49 agency tenths at 300,000 cents per hour bills 1,500,000 cents provisionally but 1,470,000 reconciled.

Closure paths are narrow. A reconciled invoice is marked paid by `AgencyFinance`, landing in terminal `PAID` with the season ledger unmoved, since `PAID` stays in the invariant set. `CarrierFinance` may void an invoice from `DRAFT`, `SUBMITTED`, or `DISPUTED`; voiding from `DRAFT` touches no ledger — a draft was never counted — while voiding from `SUBMITTED` or `DISPUTED` subtracts the invoice's `net_cents` from `season_billed_cents`, the exact compensation of the submit side effect, bumping both the invoice's and the contract's versions. `VOID` is terminal.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a contract, aircraft, crew member, inspection, availability period, incident, dispatch order, assignment, flight log, retardant load, invoice, or agency record — return `201 Created`. Operations that act on an existing resource, including every lifecycle transition, return `200 OK`. All read endpoints are authorized for the six business roles — `CarrierOps`, `AgencyDispatcher`, `Pilot`, `CarrierFinance`, `AgencyFinance`, and `CardingInspector` — abbreviated as "All business roles" below; `SystemAdmin` holds no read access and appears only on the clock capability.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/contracts` | Create a contract in DRAFT | CarrierOps |
| GET | `/contracts` | List contracts | All business roles |
| GET | `/contracts/{id}` | Get one contract | All business roles |
| POST | `/contracts/{id}/activate` | Activate a DRAFT contract | CarrierOps |
| POST | `/contracts/{id}/suspend` | Suspend an ACTIVE contract | CarrierOps |
| POST | `/contracts/{id}/resume` | Resume a SUSPENDED contract | CarrierOps |
| POST | `/contracts/{id}/close` | Close a contract with no open orders | CarrierOps |
| GET | `/contracts/{id}/availability-periods` | List a contract's availability periods | All business roles |
| GET | `/contracts/{id}/invoices` | List a contract's invoices | All business roles |
| GET | `/contracts/{id}/agency-records` | List a contract's agency records | All business roles |
| POST | `/aircraft` | Register an aircraft on a contract | CarrierOps |
| GET | `/aircraft` | List aircraft | All business roles |
| GET | `/aircraft/{id}` | Get one aircraft | All business roles |
| POST | `/aircraft/{id}/decard` | Decard an aircraft | CarrierOps |
| GET | `/aircraft/{id}/carding-inspections` | List an aircraft's inspections | All business roles |
| POST | `/crew-members` | Register a crew member on a contract | CarrierOps |
| GET | `/crew-members` | List crew members | All business roles |
| GET | `/crew-members/{id}` | Get one crew member | All business roles |
| GET | `/crew-members/{id}/duty-days` | List a crew member's duty days | All business roles |
| GET | `/crew-members/{id}/carding-inspections` | List a crew member's inspections | All business roles |
| GET | `/crew-members/{id}/flight-logs` | List a crew member's flight logs | All business roles |
| POST | `/crew-members/{id}/rest-release` | Release a crew member from fatigue hold | CarrierOps |
| POST | `/carding-inspections` | Schedule an inspection for one subject | CardingInspector |
| POST | `/carding-inspections/{id}/complete` | Complete an inspection with a result | CardingInspector |
| POST | `/carding-inspections/{id}/reschedule` | Reschedule a failed inspection | CardingInspector |
| POST | `/contracts/{id}/availability-periods` | Offer availability for an aircraft on a date | CarrierOps |
| GET | `/availability-periods` | List availability periods | All business roles |
| GET | `/availability-periods/{id}` | Get one availability period | All business roles |
| POST | `/availability-periods/{id}/confirm` | Confirm an offered day | AgencyDispatcher |
| POST | `/availability-periods/{id}/excuse` | Excuse an offered or confirmed day | CarrierOps |
| POST | `/incidents` | Report an incident | AgencyDispatcher |
| GET | `/incidents` | List incidents | All business roles |
| GET | `/incidents/{id}` | Get one incident | All business roles |
| POST | `/incidents/{id}/advance` | Advance an incident's status | AgencyDispatcher |
| POST | `/dispatch-orders` | Place a resource order | AgencyDispatcher |
| GET | `/dispatch-orders` | List dispatch orders | All business roles |
| GET | `/dispatch-orders/{id}` | Get one dispatch order | All business roles |
| POST | `/dispatch-orders/{id}/accept` | Accept a placed order | CarrierOps |
| POST | `/dispatch-orders/{id}/decline` | Decline a placed order | CarrierOps |
| POST | `/dispatch-orders/{id}/cancel` | Cancel a placed or unfilled accepted order | AgencyDispatcher |
| GET | `/dispatch-orders/{id}/assignments` | List an order's assignments | All business roles |
| POST | `/dispatch-orders/{id}/assignments` | Assign aircraft and pilot to an order | CarrierOps |
| GET | `/assignments` | List assignments | All business roles |
| GET | `/assignments/{id}` | Get one assignment | All business roles |
| POST | `/assignments/{id}/launch` | Launch an assignment | CarrierOps, Pilot |
| POST | `/assignments/{id}/arrive` | Mark arrival on incident | CarrierOps, Pilot |
| POST | `/assignments/{id}/release` | Release an assignment | AgencyDispatcher |
| POST | `/assignments/{id}/demobilize` | Demobilize a released assignment | CarrierOps |
| GET | `/assignments/{id}/flight-logs` | List an assignment's flight logs | All business roles |
| GET | `/assignments/{id}/retardant-loads` | List an assignment's retardant loads | All business roles |
| GET | `/assignments/{id}/agency-records` | List an assignment's agency records | All business roles |
| POST | `/assignments/{id}/flight-logs` | Append a sortie to an assignment | Pilot |
| POST | `/assignments/{id}/retardant-loads` | Request a retardant load | CarrierOps |
| POST | `/retardant-loads/{id}/load` | Complete a retardant load | CarrierOps |
| POST | `/retardant-loads/{id}/drop` | Record a retardant drop | CarrierOps, Pilot |
| POST | `/contracts/{id}/invoices` | Create a DRAFT invoice for a period | CarrierFinance |
| GET | `/invoices/{id}` | Get one invoice | All business roles |
| GET | `/invoices/{id}/line-items` | List an invoice's line items | All business roles |
| POST | `/invoices/{id}/submit` | Submit a closed-period invoice | CarrierFinance |
| POST | `/invoices/{id}/dispute` | Dispute a submitted invoice | AgencyFinance |
| POST | `/invoices/{id}/resubmit` | Resubmit a disputed invoice | CarrierFinance |
| POST | `/invoices/{id}/reconcile` | Reconcile against agency records | AgencyFinance |
| POST | `/invoices/{id}/mark-paid` | Mark a reconciled invoice paid | AgencyFinance |
| POST | `/invoices/{id}/void` | Void a draft, submitted, or disputed invoice | CarrierFinance |
| POST | `/agency-records` | Import an agency flight-time record | AgencyFinance |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_AIRCRAFT_NOT_FOUND` | 404 |
| `ERR_CREW_MEMBER_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_DISPATCH_ORDER_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_AVAILABILITY_PERIOD_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_RETARDANT_LOAD_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_AIRCRAFT_NOT_CARDED` | 409 |
| `ERR_CREW_NOT_CARDED` | 409 |
| `ERR_DISPATCH_ALREADY_FILLED` | 409 |
| `ERR_ASSIGNMENT_OVERLAP` | 409 |
| `ERR_AVAILABILITY_OVERLAP` | 409 |
| `ERR_INVOICE_PERIOD_OVERLAP` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CARDING_EXPIRED` | 422 |
| `ERR_CREW_ON_FATIGUE_HOLD` | 422 |
| `ERR_FLIGHT_HOUR_LIMIT_EXCEEDED` | 422 |
| `ERR_CREW_DAY_LIMIT_EXCEEDED` | 422 |
| `ERR_DUTY_REST_VIOLATION` | 422 |
| `ERR_ACCEPTANCE_WINDOW_EXPIRED` | 422 |
| `ERR_CONFIRM_WINDOW_EXPIRED` | 422 |
| `ERR_SERVICE_DATE_OUTSIDE_SEASON` | 422 |
| `ERR_BILLING_PERIOD_NOT_CLOSED` | 422 |
| `ERR_SEASON_FLIGHT_CAP_EXCEEDED` | 422 |
| `ERR_AIRCRAFT_NOT_ON_CONTRACT` | 422 |
| `ERR_PILOT_NOT_ON_CONTRACT` | 422 |
| `ERR_MODEL_MISMATCH` | 422 |
| `ERR_MODEL_NOT_QUALIFIED` | 422 |
| `ERR_TANK_CAPACITY_EXCEEDED` | 422 |
