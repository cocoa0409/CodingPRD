# Repair Café & Fix-It Clinic API — Product Requirements Document

## 1. Introduction

Community repair events live or die on logistics. A nonprofit repair café must coordinate a hall full of volunteer fixers, a stream of visitors carrying broken electronics, textiles, and bicycles, a finite stock of spare parts, and the safety obligations that come with letting the public watch — and sometimes handle — hazardous repairs. Today this coordination is done with clipboards and goodwill, which means no reliable record of what was fixed, what was diverted from landfill, which fixers actually showed up, or what a grant funder should be told at the end of the season.

This document specifies the Repair Café & Fix-It Clinic API, the back-office system for running such events end to end. It covers event setup and station management, volunteer fixer registration, skill tracking and shift scheduling, front-desk visitor intake with waivers, item triage and queueing, workbench assignment under a deterministic fixer-selection policy, parts reservation against finite stock, repair outcome recording with segregation-of-duties verification, safety incident handling with cascading suspensions, donation capture with two parallel valuation schemes, and a final per-event report that snapshots every metric a funder might ask for. All operations are evaluated against a server-maintained logical clock rather than wall-clock time, so that expiry, induction validity, and event windows are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly four roles, spelled as follows: `Coordinator`, `IntakeVolunteer`, `Fixer`, and `SafetyOfficer`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `Fixer`, `X-User-ID` is the `id` of the acting `FixerProfile`; ownership checks on any resource that references a fixer — a shift, an assigned repair item, a recorded outcome — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Coordinator`, `IntakeVolunteer`, or `SafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `reported_by_user_id` on a `SafetyIncident` or `verified_by_user_id` on a `RepairOutcome`, where transitions write it) but does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the host's wall clock (the one place the server reads wall-clock time; see §2.4).
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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, and must lie between 1 and 100 inclusive; a non-integer or out-of-range `limit` is rejected with `ERR_VALIDATION`. The `offset` parameter sets how many items to skip and defaults to 0; a non-integer or negative `offset` is rejected with `ERR_VALIDATION`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, breaking ties — common under the logical clock — by creation order, earliest created first. The `meta` object of a list response carries `limit`, `offset`, `total_count` (the size of the filtered result set), and `has_more` (true exactly when items remain beyond the returned page). List endpoints additionally accept optional filter query parameters named after fields of the listed resource (for example `event_id`, `status`, or `category`), which narrow the result set to exact matches. Each list endpoint supports a fixed set of filter parameters — events by `status`; stations by `event_id`, `status`, `category`; fixers by `status`; skills by `fixer_id`, `category`; shifts by `fixer_id`, `station_id`, `event_id`, `status`; visitors support none; waivers by `visitor_id`, `status`; items by `event_id`, `visitor_id`, `assigned_station_id`, `assigned_fixer_id`, `status`; triage records and incidents as named in §3.3 and §3.6; outcomes by `item_id`, `fixer_id`, `verification_status`; stock by `category`, `sku`; reservations by `part_stock_id`, `repair_item_id`, `status`; donations by `event_id`, `visitor_id`, `status`; and reports by `event_id` — and a filter parameter outside that set is ignored rather than rejected.

### 2.4. The Logical Clock

The server never reads wall-clock time for any business judgment (the response envelope's `api_request_timestamp`, §2.2, is the sole exception). Instead it maintains a **logical clock** whose value at startup is exactly `2026-05-01T00:00:00Z`; before any operator intervention, every timestamp comparison in the system is evaluated against that instant. A `Coordinator`-only administrative capability advances the clock: the request carries a `to_iso8601` field holding the new current instant, which must be greater than or equal to the present logical-clock value. Supplying an earlier instant is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). All temporal judgments in this document — waiver validity, induction validity, shift check-in windows, reservation expiry, donation campaign windows — are made against this logical clock. Advancing the clock does not itself rewrite any resource; time-triggered state changes (waiver expiry, reservation expiry) are re-evaluated lazily on the next access to the affected resource.

### 2.5. Validation Evaluation Order

When several rules could reject the same request, checks fire in a fixed priority order, and the first failure determines the error returned. The order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is a declared role; failures yield `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted for this endpoint; failures yield `ERR_UNAUTHORIZED_ROLE`.
3. **Existence** — path identifiers and body foreign-key identifiers must exist, validated left to right: path parameters first, then body fields in their declared order. Each resource type has its own not-found error (see §2.6).
4. **State** — the target resource is in a state that permits the requested transition, including the derived event-posture gate at intake; failures carry the entity-specific state errors enumerated throughout §3, with `ERR_INVALID_STATE` (HTTP 409) as the generic fallback when no more specific state error applies.
5. **Waiver and safety gates** — the waiver, safety-clause, induction, and open-incident checks described in §3.2, §3.4, and §3.5.
6. **Temporal shape** — shift duration limits (`ERR_SHIFT_TOO_LONG`).
7. **Fixer double-booking** — half-open shift overlap (`ERR_SHIFT_OVERLAP`).
8. **Station interval capacity at signup** — closed-interval overlap counting (`ERR_STATION_INTERVAL_CAPACITY_EXCEEDED`).
9. **Check-in window** — the current logical clock must fall inside the shift window (`ERR_SHIFT_NOT_IN_WINDOW`).
10. **Skill, reliability, and segregation-of-duties constraints** — duplicate skills, skill level and category matching, reliability threshold, active-fixer requirements, busy-fixer exclusion, verifier-not-performer, and resolver-not-reporter.
11. **Cross-reference consistency** — for example, a shift's `event_id` must equal its station's event (`ERR_EVENT_STATION_MISMATCH`).
12. **Capacity and quota checks, always last** — intake cap, station seat capacity at check-in, stock availability, and stock-below-reserved protections.

Malformed payloads — a missing required field, an invalid enum value, an out-of-range scalar, or an end timestamp that does not come after its start — are rejected with `ERR_VALIDATION` (HTTP 400). Within a request, body fields are read and validated in their declared order: each field's shape is checked (`ERR_VALIDATION` on failure) at the moment it is read, and a field that is a foreign key has its target's existence checked at the same point, so an earlier field's shape or existence failure pre-empts all later checks. Ownership checks (`ERR_FORBIDDEN_OWNERSHIP`, `ERR_NOT_ASSIGNED_FIXER`) fire as soon as the identifier they guard is available, ahead of the state and business-rule checks of steps 4–12.

### 2.6. Resource Existence and Identifier Resolution

Every entity identifier referenced by a request — whether in the URL path or in the body as a foreign key such as `event_id`, `visitor_id`, or `part_stock_id` — is checked for existence before business rules run, in the order given in §2.5 step 3. Each resource type reports its own not-found error, all with HTTP 404: `ERR_EVENT_NOT_FOUND` for a `RepairEvent`, `ERR_STATION_NOT_FOUND` for a `Station`, `ERR_FIXER_NOT_FOUND` for a `FixerProfile`, `ERR_VISITOR_NOT_FOUND` for a `Visitor`, `ERR_WAIVER_NOT_FOUND` for a `Waiver`, `ERR_ITEM_NOT_FOUND` for a `RepairItem`, `ERR_TRIAGE_NOT_FOUND` for a `TriageRecord`, `ERR_SHIFT_NOT_FOUND` for a `FixerShift`, `ERR_SKILL_NOT_FOUND` for a `FixerSkill`, `ERR_PART_STOCK_NOT_FOUND` for a `PartStock`, `ERR_RESERVATION_NOT_FOUND` for a `PartReservation`, `ERR_OUTCOME_NOT_FOUND` for a `RepairOutcome`, `ERR_INCIDENT_NOT_FOUND` for a `SafetyIncident`, `ERR_DONATION_NOT_FOUND` for a `Donation`, and `ERR_REPORT_NOT_FOUND` for an `EventReport`. A request whose path matches no endpoint at all, or whose method the matched path does not support, is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.7. Common Resource Properties

Most resources share a standard set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock (§2.4) at creation. The `updated_at` field is an ISO 8601 UTC timestamp, initialized equal to `created_at` and refreshed from the logical clock on every mutation of the resource. The `version` field is an integer that starts at 1 on creation and increments by exactly 1 on every mutation, including mutations driven by system cascades — the sole exception being the lazy waiver expiry of §3.2, which changes `status` without touching `updated_at` or `version` — and it anchors optimistic concurrency control (§2.8).

Three resources are deliberately lighter. `FixerSkill`, `TriageRecord`, and `EventReport` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, since skills are removed rather than updated, triage records are immutable once written (supersession creates a new record), and reports are frozen snapshots.

### 2.8. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and only these two. First, creating a triage record for a repair item requires the request to carry `expected_item_version`, holding the item's `version` as last observed by the client. If the item's current `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412); because re-triage legitimately supersedes the prior current record, a writer holding a stale version would otherwise silently supersede a record it never saw. Second, adjusting a part stock row requires `expected_part_stock_version` carrying the stock row's last-observed `version`; reservation commits decrement on-hand quantity and bump the version, so a stale adjustment would overwrite stock it never accounted for, and is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). On both endpoints the expected-version comparison is evaluated after the resource's existence and state checks and before the remaining business rules (for triage, after the item-state gate and before the active-fixer check; for stock adjustment, before the below-reserved check). Endpoints other than these two ignore any version field a client supplies.

### 2.9. Event Posture and Intake Gating

Every event exposes a computed `posture`, either `ACCEPTING` or `RESTRICTED`. An event is `ACCEPTING` if and only if all three conditions hold: its `status` is `INTAKE_OPEN`, at least one of its stations is `OPEN`, and no `SafetyIncident` of severity `CRITICAL` in status `REPORTED` exists for that event. Otherwise the posture is `RESTRICTED`. Posture is recomputed whenever one of its inputs changes — a station opening, pausing, resuming, or closing; an incident being reported, resolved, or dismissed; an event entering or leaving `INTAKE_OPEN` — and it gates item intake as described in §3.2.

### 2.10. Conservation Invariants

Two pools are finite and must be conserved exactly. For each `PartStock` row, the physical `quantity_on_hand` always equals the initial on-hand quantity, plus the sum of all administrative adjustment deltas applied to it, minus the sum of `quantity` over its reservations in `COMMITTED` status; and `quantity_reserved` always equals the sum of `quantity` over its reservations in `RESERVED` status. The derived `quantity_available` is `quantity_on_hand` minus `quantity_reserved`. A reserve followed by its own release must leave both `quantity_on_hand` and `quantity_reserved` unchanged. For each `Station`, the derived `checked_in_fixer_count` always equals the count of `FixerShift` rows at that station in `CHECKED_IN` status; a check-in followed by its own check-out must leave the count unchanged. These invariants are audited after every reserve, commit, release, stock adjustment, check-in, check-out, and shift cancellation.

### 2.11. Precision, Rounding, and Money

All monetary values are integers denominated in cents — fields such as `unit_cost_cents`, `cost_cents`, `amount_cents`, `parts_cost_cents`, `suggested_donation_cents`, `receipt_value_cents`, and `campaign_value_cents`. Where a multiplication produces a fractional cent, the value is rounded half-up to a whole cent, and the donation receipt calculation rounds each line before summing (never the other way around). Diversion weights are expressed in kilograms rounded half-up to one decimal place. Success rates on the event report are rounded half-up to four decimal places. Priority and reliability scores are integers requiring no rounding.

## 3. Business Logic & Workflows

### 3.1. Setting Up an Event: Stations, Fixers, and Shifts

A `Coordinator` begins by creating a **RepairEvent** with a non-empty human-readable `name`, an event window given by `starts_at` and `ends_at` (the end must be after the start), and an `intake_item_cap` of at least 1 bounding how many items may be in flight at once. New events are born in `DRAFT` status; the full lifecycle runs `DRAFT → PUBLISHED → INTAKE_OPEN → REPAIR_ACTIVE → CLOSED → REPORTED`, with `CANCELLED` reachable from any non-terminal state. Publishing moves the event from `DRAFT` to `PUBLISHED` and requires that at least one station exists for the event — an attempt with zero stations fails with `ERR_EVENT_HAS_NO_STATIONS`. Opening intake moves `PUBLISHED → INTAKE_OPEN` and requires at least one station of the event to be `OPEN`, otherwise `ERR_NO_OPEN_STATION`. Intake can be reverted (`INTAKE_OPEN → PUBLISHED`) only when no item of the event is `ASSIGNED` or `IN_REPAIR`; a violation is reported as `ERR_ITEMS_IN_FLIGHT`. Beginning repairs moves `INTAKE_OPEN → REPAIR_ACTIVE` unconditionally. Every one of these transitions increments the event's `version` by 1.

Stations are the physical benches. A `Coordinator` creates each `Station` with its hosting `event_id`, a `category` of `ELECTRONICS`, `TEXTILE`, or `BIKE`, a human `label`, and a `capacity` of at least 1 bounding how many fixers may be checked in at once. Stations are born in `SETUP`. Opening a station (`SETUP → OPEN`) requires the parent event to be in `PUBLISHED`, `INTAKE_OPEN`, or `REPAIR_ACTIVE` — opening against a `DRAFT` event fails with `ERR_INVALID_EVENT_STATE` — and requires at least one checked-in fixer at that station who holds a skill whose category matches the station's category, otherwise `ERR_NO_QUALIFIED_FIXER_CHECKED_IN`. Pausing (`OPEN → PAUSED`) is refused while any item assigned to the station is `IN_REPAIR` (`ERR_ITEMS_IN_FLIGHT`), and resuming (`PAUSED → OPEN`) re-applies the qualified-fixer requirement. Whenever the last checked-in fixer at an `OPEN` station checks out or is cancelled and `checked_in_fixer_count` falls to zero, the station automatically transitions `OPEN → PAUSED` without any client request; every open, pause, resume, and auto-pause recomputes the parent event's `posture`. A station may be closed from `SETUP` or `PAUSED` freely; closing from `OPEN` is refused while any fixer remains checked in (`ERR_STATION_HAS_CHECKED_IN_FIXERS`). Any station transition attempted from a state that does not permit it is rejected with `ERR_INVALID_STATION_STATE`.

Volunteer fixers are registered by a `Coordinator` with a `display_name`, a non-empty contact `email` that must be unique across fixers (a duplicate is rejected with `ERR_VALIDATION`), and a `safety_induction_completed_at` timestamp recording when they completed safety induction, which remains valid for 365 days. A new `FixerProfile` starts `ACTIVE` with a `reliability_score` of 100. Reliability moves only on terminal shift outcomes: a no-show costs 15 points, leaving early costs 5 points, and a completed shift earns 2 points, with the score always clamped to the range 0 through 100. A fixer whose score is below 40 may not sign up for shifts, be assigned items, or be reinstated from suspension — each such attempt fails with `ERR_RELIABILITY_TOO_LOW`.

Each fixer's competencies are recorded as `FixerSkill` rows combining a `fixer_id`, a skill `category` (`ELECTRONICS`, `TEXTILE`, or `BIKE`), a `level` between 1 and 5 inclusive, and a `certified` flag defaulting to false. The pair of fixer and category must be unique: a second skill row for the same fixer in the same category is rejected with `ERR_SKILL_DUPLICATE`. Skills can be listed and fetched by any role, and a `Coordinator` may delete one.

Shifts bind a fixer to a station for a time window. Creating a `FixerShift` takes `fixer_id`, `station_id`, `event_id`, `start_time`, and `end_time`; a `Fixer` may only sign up for themselves, so a fixer-role request whose `fixer_id` differs from `X-User-ID` is rejected with `ERR_FORBIDDEN_OWNERSHIP`, while a `Coordinator` may sign anyone up. The declared `event_id` must equal the event of the target station, otherwise `ERR_EVENT_STATION_MISMATCH`. The shift must last longer than zero seconds and no more than 21600 seconds (six hours), else `ERR_SHIFT_TOO_LONG`. A fixer's shifts must never double-book: the new half-open interval — inclusive of `start_time`, exclusive of `end_time` — must not overlap any non-cancelled shift of the same fixer, though back-to-back shifts where one's end equals the other's start are permitted; a violation yields `ERR_SHIFT_OVERLAP`. The station's schedule is checked more strictly under closed-interval semantics where touching endpoints count: the number of non-cancelled shifts at the station overlapping the new one must stay below the station's `capacity`, else `ERR_STATION_INTERVAL_CAPACITY_EXCEEDED`. Signup also applies the reliability gate — a fixer scoring below 40 is refused with `ERR_RELIABILITY_TOO_LOW` — and requires the fixer to be `ACTIVE` (`ERR_FIXER_SUSPENDED`). New shifts are `SIGNED_UP`; a `Coordinator` confirms them (`SIGNED_UP → CONFIRMED`).

Check-in (`CONFIRMED → CHECKED_IN`) is performed by the fixer themselves or by a `Coordinator` on their behalf; anyone else is refused with `ERR_FORBIDDEN_OWNERSHIP`. It requires the fixer to be `ACTIVE` (`ERR_FIXER_SUSPENDED`), the shift's event to be in `PUBLISHED`, `INTAKE_OPEN`, or `REPAIR_ACTIVE` (`ERR_EVENT_PHASE_FORBIDS`), the safety induction to be unexpired — `safety_induction_completed_at` plus 365 days must still be later than the logical clock, else `ERR_INDUCTION_EXPIRED` — the logical clock to fall inside the shift window, at or after `start_time` and strictly before `end_time` (`ERR_SHIFT_NOT_IN_WINDOW`), and a free seat at the station, meaning `checked_in_fixer_count` strictly below `capacity` (`ERR_STATION_AT_CAPACITY`). A successful check-in stamps `checked_in_at` with the logical clock and raises the station's `checked_in_fixer_count` by one.

Check-out takes a `completion` flag. With completion true the shift becomes `COMPLETED` and the fixer gains 2 reliability points (clamped at 100); with completion false it becomes `LEFT_EARLY` and costs 5 points. Either way the station's `checked_in_fixer_count` drops by one, and if it reaches zero the station auto-pauses as described above. Shifts may also be cancelled from `SIGNED_UP` or `CONFIRMED` by the fixer or a `Coordinator`; a shift transition attempted from a state that does not permit it fails with `ERR_INVALID_SHIFT_STATE`.

### 3.2. Front Desk: Visitors, Waivers, and Item Intake

An `IntakeVolunteer` registers each visitor with a `full_name` and `email`, plus an optional `phone` defaulting to empty. Before any item can be accepted, the visitor must sign a **Waiver**: signing records the `visitor_id`, stamps `signed_at` from the logical clock, captures whether the hazardous-item safety clause was accepted via `safety_clause_accepted` (defaulting to false), and creates the waiver in `ACTIVE` status. A waiver is valid only while it is `ACTIVE` and fewer than 365 days have elapsed since `signed_at` — that is, `signed_at` plus 365 days must still be later than the current logical clock. A waiver observed past that point lazily transitions to `EXPIRED`; this lazy transition changes `status` only, without refreshing `updated_at` or incrementing `version`. A visitor may hold any number of waivers. A `SafetyOfficer` or `Coordinator` may revoke an `ACTIVE` waiver (`ACTIVE → REVOKED`); revoking one that is not `ACTIVE` fails with `ERR_INVALID_WAIVER_STATE`.

Item intake is the front desk's central act. The volunteer submits the hosting `event_id`, the owning `visitor_id`, the item's `category` (`ELECTRONICS`, `TEXTILE`, or `BIKE`), a free-text `description` of the problem, an optional `hazard_flag` (defaulting to false) marking mains-powered, fuel-bearing, sharps-containing, or similarly dangerous items, and a `weight_kg_estimated` of at least 0.1 kilograms. Intake is gated by a layered set of checks. The event must be in `INTAKE_OPEN` status (`ERR_EVENT_NOT_ACCEPTING_INTAKE`), and its derived `posture` must be `ACCEPTING` — intake during a `RESTRICTED` posture, whether caused by the absence of any open station or by an open `CRITICAL` incident, is refused with `ERR_POSTURE_RESTRICTED`. The visitor must hold at least one currently valid waiver: when none is valid, the failure is `ERR_WAIVER_EXPIRED` if at least one of the visitor's waivers has lapsed (the lazy `EXPIRED` transition fires as part of this check) and `ERR_WAIVER_REQUIRED` otherwise — including when every waiver they hold is `REVOKED`. When `hazard_flag` is true, at least one currently valid waiver must have `safety_clause_accepted` set, else `ERR_WAIVER_SAFETY_CLAUSE_REQUIRED`. Finally, capacity is enforced: the event's `active_item_count` — the count of its items in `REGISTERED`, `TRIAGED`, `QUEUED`, `ASSIGNED`, `IN_REPAIR`, or `OUTCOME_RECORDED` — must be below `intake_item_cap`, or intake fails with `ERR_INTAKE_CAP_REACHED`. A successfully accepted item is born in `REGISTERED` status and raises `active_item_count` by one.

### 3.3. Triage and the Repair Queue

Triage turns a registered item into prioritized work. A `Fixer` creates a **TriageRecord** for an item by supplying a `severity` between 1 and 10, an `estimated_difficulty` between 1 and 5, and a free-text `diagnosis`; the acting fixer's identity is recorded as the record's `assessor_fixer_id`; the acting fixer's `X-User-ID` must identify an existing `FixerProfile`, else `ERR_FIXER_NOT_FOUND`. Triage is accepted only while the item is `REGISTERED`, `TRIAGED`, or `QUEUED`; any other item status fails with `ERR_INVALID_ITEM_STATE`. This is an optimistic-concurrency write: the request must carry `expected_item_version` matching the item's current `version`, or it is rejected with `ERR_STALE_VERSION` as specified in §2.8. The acting fixer must be `ACTIVE` (`ERR_FIXER_SUSPENDED`).

The first triage moves the item `REGISTERED → TRIAGED`. Every triage creation — first or subsequent — recomputes the item's `priority_score`: start from a category base of 10 points for `ELECTRONICS`, 5 for `TEXTILE`, and 7 for `BIKE`; add 8 points per unit of `severity`; add 2 points per unit of `estimated_difficulty`; add a further 15 points when the item's `hazard_flag` is set; then clamp the total into the range 0 through 100. Before any triage the score is 0. The item's `required_skill_level` is set equal to the triage record's `estimated_difficulty` (0 before triage).

Re-triage is explicitly supported and supersedes rather than edits. A new triage on a `TRIAGED` item keeps it `TRIAGED`; a new triage on a `QUEUED` item keeps it `QUEUED`. In both cases the previously current record's `superseded_by_id` is set to the new record's `id` and its `is_current` flag becomes false, while the new record is the one with `is_current` true; priority and required-skill fields are recomputed from the new record. Triage records are immutable history — they carry no `version` — and can be listed with filters on `item_id`, `assessor_fixer_id`, or `superseded_by_id`. Whenever a triage record's `severity` is 8 or higher, the system automatically creates a `SafetyIncident` of severity `CRITICAL` linked to the item and its event, with no subject (`fixer_id` is null), a server-generated description, and `reported_by_user_id` set to the acting fixer's id, and recomputes the event's `posture` — which, since a `CRITICAL` reported incident now exists, flips intake to `RESTRICTED`. Every triage transition increments the item's `version` by 1.

A `Coordinator` enqueues a triaged item (`TRIAGED → QUEUED`) when it is ready to wait for a bench. Queueing is also where items return after setbacks, as the following sections describe.

### 3.4. Assignment, the Workbench, and the Parts Bin

Assignment (`QUEUED → ASSIGNED`) is performed by a `Coordinator`, optionally naming a `fixer_id` and `station_id`, or omitting them to invoke auto-selection; attempted on an item not `QUEUED`, it fails with `ERR_INVALID_ITEM_STATE`. The preconditions are extensive and all enforced. The event must be in `INTAKE_OPEN` or `REPAIR_ACTIVE` (`ERR_EVENT_PHASE_FORBIDS`). The target station must be `OPEN` (`ERR_STATION_NOT_OPEN`); its `category` must equal the item's `category` — a station-category mismatch is reported as `ERR_SKILL_MISMATCH` — and it must belong to the same event as the item — an event mismatch reported as `ERR_EVENT_STATION_MISMATCH`; when both would fail, the category check fires first. The chosen fixer must be checked in at that station — a named fixer who is not is reported as `ERR_NO_ELIGIBLE_FIXER`, the same error as an empty auto-selection pool; must hold a skill whose category matches the item's `category` (`ERR_SKILL_MISMATCH` when no such skill exists) with a `level` at least the item's `required_skill_level` (`ERR_SKILL_LEVEL_INSUFFICIENT` when the level falls short); must carry a `reliability_score` of at least 40 (`ERR_RELIABILITY_TOO_LOW`); must be `ACTIVE` (`ERR_FIXER_SUSPENDED`); and must not already have another item in `ASSIGNED` or `IN_REPAIR` (`ERR_FIXER_BUSY`).

When `fixer_id` is omitted, the selector policy considers the fixers checked in at the candidate stations — the named station when `station_id` is given, otherwise every `OPEN` station of the item's event whose category matches the item — and ranks the eligible pool by `reliability_score` descending, breaking ties by the fixer's shift `checked_in_at` ascending — earlier check-ins first — and any remaining ties by shift creation order, earliest created first, and picks the leader. A fixer checked in at several candidate stations is represented by their earliest-checked-in shift, which also determines the assigned station; the same rule chooses the station when `fixer_id` is named without a `station_id`. An empty eligible pool is reported as `ERR_NO_ELIGIBLE_FIXER`. A successful assignment writes the item's `assigned_fixer_id` and `assigned_station_id`, which remain null outside `ASSIGNED` and `IN_REPAIR`.

The assigned fixer — and only that fixer, identified by comparing `X-User-ID` to `assigned_fixer_id` (`ERR_NOT_ASSIGNED_FIXER`) — starts the repair (`ASSIGNED → IN_REPAIR`). From there the item can be sent back to the queue (`IN_REPAIR → QUEUED`) by the assigned fixer, by a `Coordinator`, or by the system during a suspension cascade; return-to-queue clears both assigned fields but deliberately keeps any `RESERVED` part reservations attached to the item. A `Coordinator` may also unassign (`ASSIGNED → QUEUED`), clearing the assigned fields. Start-repair, return-to-queue, and unassign each fail with `ERR_INVALID_ITEM_STATE` when attempted from any item state other than the one named.

Parts are managed as **PartStock** rows created by a `Coordinator` with a unique, non-empty `sku` (a duplicate is rejected with `ERR_VALIDATION`), a `name`, a `category` (one of `ELECTRONICS`, `TEXTILE`, `BIKE`, or `GENERIC`), a `unit_cost_cents` of at least 0, and a `quantity_on_hand` of at least 0. A `Coordinator` adjusts a stock row's `quantity_on_hand` or `unit_cost_cents` through the stock-adjustment write, which is the second OCC-protected operation: it requires `expected_part_stock_version` matching the row's current `version`, rejected with `ERR_STALE_VERSION` on mismatch, and it may never push `quantity_on_hand` below the live `quantity_reserved` (`ERR_STOCK_BELOW_RESERVED`). Either field may be omitted from an adjustment, in which case it is left unchanged, and the row's `version` increments only when a supplied value actually differs from the stored one.

Reserving parts creates a **PartReservation** from a `part_stock_id`, the `repair_item_id` it is reserved for (which must belong to a non-terminal repair flow, in `ASSIGNED` or `IN_REPAIR`), and a `quantity` of at least 1. The stock's `quantity_available` must cover the request, else `ERR_INSUFFICIENT_STOCK`. The reservation snapshots the stock's `unit_cost_cents` at creation, computes its own `cost_cents` as `quantity` times that snapshot, starts in `RESERVED`, and sets `expires_at` to the `ends_at` of the item's event. Committing a reservation (`RESERVED → COMMITTED`) requires the logical clock to be at or before `expires_at` — a commit attempted past expiry is rejected with `ERR_RESERVATION_EXPIRED` without flipping the reservation's status — and requires that no `SafetyIncident` of severity `HIGH` or `CRITICAL` in status `REPORTED` exists for the item (`ERR_SAFETY_HOLD`). A commit decrements the stock's `quantity_on_hand` by the reserved `quantity`, bumps the stock row's `version` by 1, and recomputes `quantity_reserved`, `quantity_available`, and the event's `parts_committed_cents` (the sum of `cost_cents` over `COMMITTED` reservations of the event's items). Releasing (`RESERVED → RELEASED`) frees availability again — `quantity_reserved` and `quantity_available` recomputed, `quantity_on_hand` untouched. Reservations also reach `EXPIRED`, but only at the event-close checkpoint of §3.7, never from the clock alone. Commit or release attempted on a reservation no longer `RESERVED` fails with `ERR_INVALID_RESERVATION_STATE`.

### 3.5. Outcomes, Verification, and Diversion Accounting

When the bench work ends, the assigned fixer records a **RepairOutcome** (`IN_REPAIR → OUTCOME_RECORDED`), supplying the `outcome` — `FIXED`, `PARTIALLY_FIXED`, or `NOT_REPAIRABLE` — and optionally a `weight_kg_actual` scale weight (a number of at least 0 when present); when the actual weight is absent, all diversion math falls back to the item's `weight_kg_estimated`. The acting fixer must be the item's assignee (`ERR_NOT_ASSIGNED_FIXER`), and their identity is stored as the outcome's `fixer_id`. The outcome is born with `verification_status` `RECORDED`. Two money fields are computed at recording time. The `parts_cost_cents` is the sum of `cost_cents` over the item's `COMMITTED` reservations. The `suggested_donation_cents` is computed in a pinned order: take a category base of 1500 cents for `ELECTRONICS`, 800 cents for `TEXTILE`, or 1000 cents for `BIKE`; choose the parts-share rate keyed on that base alone — one half when the base is below 1000 cents, three fifths when it is below 1500 cents, three quarters otherwise; multiply `parts_cost_cents` by that rate and round half-up to whole cents to get the share; the suggestion is then the smaller of 5000 cents and the base plus the share. Recording an outcome also recomputes the event's projected diversion figure.

Verification enforces segregation of duties. A `Coordinator` — or a `Fixer`, but never the performer — verifies an outcome (`RECORDED → VERIFIED`), which simultaneously moves the item from `OUTCOME_RECORDED` to `VERIFIED`. Verification requires the outcome to be `RECORDED` (`ERR_INVALID_OUTCOME_STATE`), requires that a fixer acting as verifier is not the outcome's `fixer_id` (`ERR_SELF_VERIFICATION_FORBIDDEN`), and requires that no `SafetyIncident` of any severity in status `REPORTED` exists for the item (`ERR_SAFETY_HOLD`). The verifier's identity is written to `verified_by_user_id`. Rejection (`RECORDED → REJECTED`) is a `Coordinator`-only act that sends the item back to `QUEUED` with its assigned fields cleared. Both transitions increment the outcome's and item's versions as recorded mutations.

Diversion from landfill is reported in two variants, each in kilograms rounded half-up to one decimal place, the rounding applied to the summed figure rather than to individual contributions. Each outcome contributes its effective weight — `weight_kg_actual` when set, otherwise the item's `weight_kg_estimated` — in full when the outcome is `FIXED`, at half weight when `PARTIALLY_FIXED`, and at zero when `NOT_REPAIRABLE`. The event's `diversion_kg_verified` sums contributions over `VERIFIED` outcomes only and is recomputed at verification; the event's `diversion_kg_projected` additionally includes outcomes still in `RECORDED`, is recomputed at outcome recording, and diverges from the verified figure whenever any outcome awaits verification.

An item declared beyond repair is not necessarily finished. When the latest outcome for an item (by creation time) is `NOT_REPAIRABLE` and still `RECORDED`, a `Coordinator` may reopen the item (`OUTCOME_RECORDED → QUEUED`) for a second opinion; the outcome record itself is left in `RECORDED` for audit. Reopening under any other condition fails with `ERR_INVALID_ITEM_STATE`. At any point before termination, an `IntakeVolunteer` or `Coordinator` may withdraw an item (any non-terminal state → `WITHDRAWN`, including from `OUTCOME_RECORDED`); withdrawal releases any `RESERVED` reservations for the item, recomputes stock figures, clears assigned fields when leaving `ASSIGNED` or `IN_REPAIR`, and refreshes the event's `active_item_count`.

### 3.6. Safety Incidents, Suspensions, and Their Cascades

Anyone in an operational role — `Coordinator`, `Fixer`, or `SafetyOfficer` — may report a **SafetyIncident** against an `event_id`, optionally linking an `item_id` and a subject `fixer_id`, with a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` and a free-text `description`. The reporter's identity is stored as `reported_by_user_id`, and the incident is born `REPORTED`. Reporting a `CRITICAL` incident immediately recomputes the event's `posture`, which suspends intake. Incidents can be listed filtered by `event_id`, `item_id`, `fixer_id`, or `status`.

Resolution is the exclusive province of a `SafetyOfficer`, and segregation of duties applies: the resolver must not be the reporter, on pain of `ERR_SEGREGATION_OF_DUTIES`. Resolving records a `resolution_action` of `NONE`, `WARNING`, or `SUSPENSION` (null until resolution); choosing `SUSPENSION` requires the incident's `fixer_id` to be set, and its absence fails with `ERR_VALIDATION`; a `SUSPENSION` resolution applies the cascade whatever the subject fixer's current status. Dismissal (`REPORTED → DISMISSED`) carries the same not-the-reporter rule. Either terminal transition recomputes the event's `posture`, so clearing the last open `CRITICAL` incident can return intake to `ACCEPTING`. Acting on an incident no longer `REPORTED` fails with `ERR_INVALID_INCIDENT_STATE`.

A `SUSPENSION` resolution — or a direct suspension of a fixer by a `SafetyOfficer` (`ACTIVE → SUSPENDED`) — triggers the system's deepest cascade, four hops deep. Hop 1: the `FixerProfile` becomes `SUSPENDED`. Hop 2: every non-terminal `FixerShift` of that fixer becomes `CANCELLED`. Hop 3: each of those shifts that was `CHECKED_IN` decrements its station's `checked_in_fixer_count`. Hop 4: any station whose count thereby reaches zero auto-transitions from `OPEN` to `PAUSED`, recomputing event posture. In the same cascade, every item assigned to that fixer in `ASSIGNED` or `IN_REPAIR` returns to `QUEUED` with its assigned fields cleared.

Suspended fixers can be reinstated (`SUSPENDED → ACTIVE`) by a `SafetyOfficer`, but only when `reliability_score` is at least 40 (`ERR_RELIABILITY_TOO_LOW`). A `Coordinator` may instead deactivate an `ACTIVE` fixer (`ACTIVE → INACTIVE`, terminal), which is refused while the fixer holds any shift in `SIGNED_UP`, `CONFIRMED`, or `CHECKED_IN`, or any item in `ASSIGNED` or `IN_REPAIR` (`ERR_ITEMS_IN_FLIGHT`). Any fixer transition attempted from a state that does not permit it is rejected with `ERR_INVALID_FIXER_STATE`.

### 3.7. Closing the Books: Event Close, Cancellation, and Reporting

Closing an event (`REPAIR_ACTIVE → CLOSED`) is the ops-run checkpoint and is allowed only when every item of the event is terminal — `VERIFIED` or `WITHDRAWN` — otherwise `ERR_EVENT_NOT_CLOSABLE`. The checkpoint sweeps the whole event in one atomic act: every shift still `CONFIRMED` becomes `NO_SHOW` and its fixer loses 15 reliability points; every shift still `CHECKED_IN` becomes `LEFT_EARLY` and loses 5; shifts still `SIGNED_UP` are left unchanged; every part reservation still `RESERVED` on an item of the event becomes `EXPIRED`, with stock `quantity_reserved` recomputed; and every station in `SETUP`, `OPEN`, or `PAUSED` becomes `CLOSED`. The event's `version` increments as usual.

Cancellation (`→ CANCELLED`) is available from every non-terminal event state — `DRAFT`, `PUBLISHED`, `INTAKE_OPEN`, `REPAIR_ACTIVE`, and `CLOSED` — and runs a full teardown cascade: every non-terminal item of the event becomes `WITHDRAWN` (items already `VERIFIED` or `WITHDRAWN` are unchanged); every `RESERVED` reservation on those items becomes `RELEASED` with stock figures recomputed; every station becomes `CLOSED`; and every non-terminal shift becomes `CANCELLED`.

Only a `CLOSED` event can be reported (`CLOSED → REPORTED`, a terminal state), and only once — a second report attempt fails with `ERR_INVALID_EVENT_STATE`. Reporting mints an **EventReport** snapshot whose `event_id` links it to the event and whose `generated_at` stamps the logical clock at generation; the endpoint responds `201 Created` with the minted `EventReport` in the `data` field. Every metric is computed at that instant and frozen: `items_total` counts the event's items holding a `VERIFIED` outcome; `items_fixed`, `items_partially_fixed`, and `items_not_repairable` break that count down by `outcome`. Two success rates follow, each rounded half-up to four decimal places and each defined as 0 when `items_total` is 0: `success_rate_strict` divides `items_fixed` by `items_total`, while `success_rate_lenient` adds half of `items_partially_fixed` to the numerator before dividing. The report also snapshots `diversion_kg_verified` and `diversion_kg_projected` from the event, records the event's committed parts spend as `parts_cost_total_cents`, and aggregates donations: `donations_receipt_total_cents` sums `receipt_value_cents` over the event's donations in `RECEIPTED` status, while `donations_campaign_total_cents` sums `campaign_value_cents` over donations in `RECEIVED` or `RECEIPTED`.

### 3.8. Donations and Fundraising

An `IntakeVolunteer` records each **Donation** as a pledge, optionally attributed to an `event_id` and to a donor `visitor_id` (anonymous donations leave it null). The `donation_type` is either `MONETARY`, which requires an `amount_cents` of at least 1, or `IN_KIND`, which requires a non-empty `in_kind_lines` array whose entries each carry a `description`, a `category` (free text, not constrained to the repair categories), a `declared_value_cents` of at least 0, and an `age_years` of at least 0. Fields belonging to the other donation type — `in_kind_lines` on a monetary pledge, `amount_cents` on an in-kind pledge — are ignored and stored as null. Pledges are born `PLEDGED`.

Receipt (`PLEDGED → RECEIVED`) stamps `received_at` from the logical clock and computes — then freezes — two parallel valuations. The tax value, `receipt_value_cents`, equals `amount_cents` for a monetary gift; for an in-kind gift, each line's declared value is multiplied by an age multiplier — 0.8 when `age_years` is at most 1, 0.5 when at most 4, and 0.2 beyond that — each line is rounded half-up to whole cents first, and only then are the lines summed. The `campaign_value_cents` rewards timeliness and generosity differently: a monetary donation counts double when `received_at` falls inside the linked event's window, from `starts_at` through `ends_at` inclusive, and counts at face value otherwise; an in-kind donation counts at the full sum of declared values with no depreciation and no per-line rounding. A `RECEIVED` donation may then be receipted (`RECEIVED → RECEIPTED`) by an `IntakeVolunteer`, or refunded (`RECEIVED → REFUNDED`) by a `Coordinator` as a compensation that removes it from campaign totals and forecloses any receipt; refunding after a receipt has been issued, receiving twice, or any other out-of-state donation transition fails with `ERR_INVALID_DONATION_STATE`.

## 4. Endpoint Definitions

All resources are mounted under the `/api` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`; deletion returns `204 No Content`. The request and response shapes of each endpoint are defined by the narratives in §2 and §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock to `to_iso8601` | Coordinator |
| POST | `/api/repair-events` | Create an event (DRAFT) | Coordinator |
| GET | `/api/repair-events` | List events | All roles |
| GET | `/api/repair-events/{id}` | Get an event incl. computed posture and diversion fields | All roles |
| POST | `/api/repair-events/{id}/publish` | DRAFT → PUBLISHED | Coordinator |
| POST | `/api/repair-events/{id}/open-intake` | PUBLISHED → INTAKE_OPEN | Coordinator |
| POST | `/api/repair-events/{id}/close-intake` | INTAKE_OPEN → PUBLISHED (revert) | Coordinator |
| POST | `/api/repair-events/{id}/begin-repairs` | INTAKE_OPEN → REPAIR_ACTIVE | Coordinator |
| POST | `/api/repair-events/{id}/close` | REPAIR_ACTIVE → CLOSED with ops-run checkpoint sweeps | Coordinator |
| POST | `/api/repair-events/{id}/cancel` | Any non-terminal state → CANCELLED with full cascade | Coordinator |
| POST | `/api/repair-events/{id}/report` | CLOSED → REPORTED; generate the EventReport snapshot | Coordinator |
| POST | `/api/stations` | Create a station (SETUP) | Coordinator |
| GET | `/api/stations` | List stations | All roles |
| GET | `/api/stations/{id}` | Get a station | All roles |
| POST | `/api/stations/{id}/open` | SETUP → OPEN | Coordinator |
| POST | `/api/stations/{id}/pause` | OPEN → PAUSED | Coordinator |
| POST | `/api/stations/{id}/resume` | PAUSED → OPEN | Coordinator |
| POST | `/api/stations/{id}/close` | Any non-terminal state → CLOSED | Coordinator |
| POST | `/api/fixer-profiles` | Register a fixer (ACTIVE, reliability 100) | Coordinator |
| GET | `/api/fixer-profiles` | List fixers | All roles |
| GET | `/api/fixer-profiles/{id}` | Get a fixer | All roles |
| POST | `/api/fixer-profiles/{id}/suspend` | ACTIVE → SUSPENDED with cascade | SafetyOfficer |
| POST | `/api/fixer-profiles/{id}/reinstate` | SUSPENDED → ACTIVE (reliability gate) | SafetyOfficer |
| POST | `/api/fixer-profiles/{id}/deactivate` | ACTIVE → INACTIVE | Coordinator |
| POST | `/api/fixer-skills` | Add a skill; (fixer, category) unique | Coordinator |
| GET | `/api/fixer-skills` | List skills | All roles |
| GET | `/api/fixer-skills/{id}` | Get a skill | All roles |
| DELETE | `/api/fixer-skills/{id}` | Remove a skill | Coordinator |
| POST | `/api/fixer-shifts` | Sign up a shift (SIGNED_UP); fixers only for themselves | Coordinator, Fixer |
| GET | `/api/fixer-shifts` | List shifts | All roles |
| GET | `/api/fixer-shifts/{id}` | Get a shift | All roles |
| POST | `/api/fixer-shifts/{id}/confirm` | SIGNED_UP → CONFIRMED | Coordinator |
| POST | `/api/fixer-shifts/{id}/check-in` | CONFIRMED → CHECKED_IN | Coordinator, Fixer |
| POST | `/api/fixer-shifts/{id}/check-out` | CHECKED_IN → COMPLETED or LEFT_EARLY per `completion` | Coordinator, Fixer |
| POST | `/api/fixer-shifts/{id}/cancel` | SIGNED_UP/CONFIRMED → CANCELLED | Coordinator, Fixer |
| POST | `/api/visitors` | Register a visitor | IntakeVolunteer |
| GET | `/api/visitors` | List visitors | All roles |
| GET | `/api/visitors/{id}` | Get a visitor | All roles |
| POST | `/api/waivers` | Sign a waiver (ACTIVE) | IntakeVolunteer |
| GET | `/api/waivers` | List waivers | All roles |
| GET | `/api/waivers/{id}` | Get a waiver | All roles |
| POST | `/api/waivers/{id}/revoke` | ACTIVE → REVOKED | Coordinator, SafetyOfficer |
| POST | `/api/repair-items` | Intake an item (REGISTERED) | IntakeVolunteer |
| GET | `/api/repair-items` | List items | All roles |
| GET | `/api/repair-items/{id}` | Get an item | All roles |
| POST | `/api/repair-items/{id}/triage-records` | Create a triage record (first or superseding; OCC) | Fixer |
| GET | `/api/triage-records` | List triage records | All roles |
| GET | `/api/triage-records/{id}` | Get a triage record | All roles |
| POST | `/api/repair-items/{id}/enqueue` | TRIAGED → QUEUED | Coordinator |
| POST | `/api/repair-items/{id}/assign` | QUEUED → ASSIGNED; omit fixer/station for auto-select | Coordinator |
| POST | `/api/repair-items/{id}/start-repair` | ASSIGNED → IN_REPAIR (assigned fixer only) | Fixer |
| POST | `/api/repair-items/{id}/return-to-queue` | IN_REPAIR → QUEUED; keeps part reservations | Coordinator, Fixer |
| POST | `/api/repair-items/{id}/unassign` | ASSIGNED → QUEUED | Coordinator |
| POST | `/api/repair-items/{id}/reopen` | Reopen a NOT_REPAIRABLE item for a second opinion | Coordinator |
| POST | `/api/repair-items/{id}/withdraw` | Any non-terminal state → WITHDRAWN | Coordinator, IntakeVolunteer |
| POST | `/api/repair-items/{id}/outcomes` | Record a repair outcome (IN_REPAIR → OUTCOME_RECORDED) | Fixer |
| GET | `/api/repair-outcomes` | List outcomes | All roles |
| GET | `/api/repair-outcomes/{id}` | Get an outcome | All roles |
| POST | `/api/repair-outcomes/{id}/verify` | RECORDED → VERIFIED; verifier ≠ performer | Coordinator, Fixer |
| POST | `/api/repair-outcomes/{id}/reject` | RECORDED → REJECTED; item back to QUEUED | Coordinator |
| POST | `/api/part-stocks` | Create a stock row | Coordinator |
| GET | `/api/part-stocks` | List stock | All roles |
| GET | `/api/part-stocks/{id}` | Get a stock row | All roles |
| PATCH | `/api/part-stocks/{id}` | Adjust stock (OCC); on-hand never below reserved | Coordinator |
| POST | `/api/part-reservations` | Reserve parts for an ASSIGNED or IN_REPAIR item | Coordinator, Fixer |
| GET | `/api/part-reservations` | List reservations | All roles |
| GET | `/api/part-reservations/{id}` | Get a reservation | All roles |
| POST | `/api/part-reservations/{id}/commit` | RESERVED → COMMITTED; decrements on-hand; safety hold applies | Coordinator, Fixer |
| POST | `/api/part-reservations/{id}/release` | RESERVED → RELEASED; frees availability | Coordinator, Fixer |
| POST | `/api/safety-incidents` | Report an incident (REPORTED) | Coordinator, Fixer, SafetyOfficer |
| GET | `/api/safety-incidents` | List incidents | All roles |
| GET | `/api/safety-incidents/{id}` | Get an incident | All roles |
| POST | `/api/safety-incidents/{id}/resolve` | REPORTED → RESOLVED; resolver ≠ reporter; SUSPENSION cascades | SafetyOfficer |
| POST | `/api/safety-incidents/{id}/dismiss` | REPORTED → DISMISSED; dismisser ≠ reporter | SafetyOfficer |
| POST | `/api/donations` | Record a pledge (PLEDGED) | IntakeVolunteer |
| GET | `/api/donations` | List donations | All roles |
| GET | `/api/donations/{id}` | Get a donation | All roles |
| POST | `/api/donations/{id}/receive` | PLEDGED → RECEIVED; computes and freezes both valuations | IntakeVolunteer |
| POST | `/api/donations/{id}/receipt` | RECEIVED → RECEIPTED | IntakeVolunteer |
| POST | `/api/donations/{id}/refund` | RECEIVED → REFUNDED (not after receipt) | Coordinator |
| GET | `/api/event-reports` | List event reports | All roles |
| GET | `/api/event-reports/{id}` | Get an event report | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_ASSIGNED_FIXER` | 403 |
| `ERR_SELF_VERIFICATION_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_CLOCK_REGRESSION` | 422 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_FIXER_NOT_FOUND` | 404 |
| `ERR_VISITOR_NOT_FOUND` | 404 |
| `ERR_WAIVER_NOT_FOUND` | 404 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_TRIAGE_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_SKILL_NOT_FOUND` | 404 |
| `ERR_PART_STOCK_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_OUTCOME_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_DONATION_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_EVENT_STATE` | 409 |
| `ERR_EVENT_HAS_NO_STATIONS` | 409 |
| `ERR_NO_OPEN_STATION` | 409 |
| `ERR_EVENT_NOT_ACCEPTING_INTAKE` | 409 |
| `ERR_POSTURE_RESTRICTED` | 409 |
| `ERR_EVENT_PHASE_FORBIDS` | 409 |
| `ERR_EVENT_NOT_CLOSABLE` | 409 |
| `ERR_INVALID_STATION_STATE` | 409 |
| `ERR_NO_QUALIFIED_FIXER_CHECKED_IN` | 409 |
| `ERR_STATION_HAS_CHECKED_IN_FIXERS` | 409 |
| `ERR_STATION_NOT_OPEN` | 409 |
| `ERR_INVALID_ITEM_STATE` | 409 |
| `ERR_ITEMS_IN_FLIGHT` | 409 |
| `ERR_INVALID_SHIFT_STATE` | 409 |
| `ERR_INVALID_OUTCOME_STATE` | 409 |
| `ERR_INVALID_RESERVATION_STATE` | 409 |
| `ERR_RESERVATION_EXPIRED` | 409 |
| `ERR_INVALID_DONATION_STATE` | 409 |
| `ERR_INVALID_WAIVER_STATE` | 409 |
| `ERR_INVALID_INCIDENT_STATE` | 409 |
| `ERR_INVALID_FIXER_STATE` | 409 |
| `ERR_WAIVER_REQUIRED` | 422 |
| `ERR_WAIVER_EXPIRED` | 422 |
| `ERR_WAIVER_SAFETY_CLAUSE_REQUIRED` | 422 |
| `ERR_INDUCTION_EXPIRED` | 422 |
| `ERR_SAFETY_HOLD` | 409 |
| `ERR_SHIFT_TOO_LONG` | 422 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_STATION_INTERVAL_CAPACITY_EXCEEDED` | 409 |
| `ERR_SHIFT_NOT_IN_WINDOW` | 409 |
| `ERR_STATION_AT_CAPACITY` | 409 |
| `ERR_SKILL_DUPLICATE` | 409 |
| `ERR_SKILL_MISMATCH` | 409 |
| `ERR_SKILL_LEVEL_INSUFFICIENT` | 409 |
| `ERR_RELIABILITY_TOO_LOW` | 409 |
| `ERR_FIXER_SUSPENDED` | 409 |
| `ERR_FIXER_BUSY` | 409 |
| `ERR_NO_ELIGIBLE_FIXER` | 409 |
| `ERR_EVENT_STATION_MISMATCH` | 422 |
| `ERR_INTAKE_CAP_REACHED` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_STOCK_BELOW_RESERVED` | 409 |
| `ERR_STALE_VERSION` | 412 |
