# Street Sweeping Schedule API — Product Requirements Document

## 1. Introduction

Municipal street-sweeping programs juggle a surprising number of moving parts: a rotating calendar of posted no-parking windows, physical signage that must be posted and field-verified before any ticket can be written, a fleet of sweeper units whose hoppers can only hold so much debris, license-plate-reader (LPR) citations that must survive a fair contest-and-adjudication process, and seasonal suspensions for holidays and leaf-fall that ripple across the entire schedule. This document specifies the Street Sweeping Schedule API, the backend system that coordinates all of these concerns behind a single flat REST surface.

The system is organized around a small set of peer resources — routes and their blocks, sweeper equipment and the shifts worked on them, the individual sweep events on the calendar, seasonal suspensions, LPR citations, residents, and complaints — linked by foreign keys carried in request bodies rather than nested deeply in URLs. Its two defining characteristics are *temporal windowing* (posted restriction windows, occupation windows, shift buffers, and date-scoped suspensions all reason about half-open time intervals) and *compliance audit* (every citation carries a defensible ledger position, and the officer who writes a ticket may never be the one who adjudicates its contest). Because so many operations trigger cascading side effects across several entities at once — activating a suspension can suspend dozens of scheduled sweeps and, in turn, dismiss the citations tied to them — the specification places heavy emphasis on stating each cascade precisely.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows:

- `PublicWorksAdmin` — creates holiday and leaf-season suspensions and drives their activation and lifting.
- `RouteDispatcher` — owns routes, blocks, equipment, shifts, the sweep calendar, resident registration, and complaint disposition.
- `SignageInspector` — posts and verifies restriction signage.
- `EnforcementOfficer` — coordinates LPR citations end to end: issue, contest, adjudicate, and pay.
- `Resident` — files and reopens complaints about their own block.

Four of these roles carry an **opaque** identity. When `X-User-Role` is `PublicWorksAdmin`, `RouteDispatcher`, `SignageInspector`, or `EnforcementOfficer`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow calls for it — for example, an `EnforcementOfficer`'s `X-User-ID` is written to a citation's `issuing_officer_id` at issuance and to `adjudicator_id` at adjudication — but it never compares it against any entity's `id` for ownership purposes.

The `Resident` role is different: its identity is **entity-backed**. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident` entity. Any ownership check on a resource that references a resident compares that resource's resident foreign key to `X-User-ID`. Concretely, filing a complaint requires that the `resident_id` in the body equal `X-User-ID`, and reopening a resolved complaint requires that the complaint's `resident_id` equal `X-User-ID`. A resident acting on a complaint that is not their own is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

All read endpoints (every `GET`) are available to all five roles. The logical-clock test-driving endpoint is available to every role except `Resident`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Out-of-range values are clamped rather than rejected: a `limit` below 1 is clamped up to 1, a `limit` above 100 is clamped down to 100, and a negative `offset` is clamped up to 0. A `limit` or `offset` that is present but not an integer is rejected with `ERR_VALIDATION` (422).

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list response carries the pagination bookkeeping in the `meta` object of the envelope, exposing `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned in the current page is strictly less than `total_count`.

### 2.4. Common Resource Properties

Every persisted resource in this system — routes, blocks, equipment, shifts, sweep events, suspensions, citations, residents, and complaints — is a top-level resource that carries the same four system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, likewise with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that begins at 1 upon creation and increments by one on every mutation of the resource. It underpins the optimistic-concurrency mechanism described in §2.6.

Whenever a derived field is recomputed on a resource — a route's `completed_block_count`, a shift's `total_debris_lbs`, `gross_tonnage`, or `net_tonnage`, or a block's `pending_citation_cents` and `sign_enforceable` — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the resource that owns the field. There are no immutable-after-creation resources in this domain; all nine entity types carry the full quartet above.

### 2.5. The Logical Clock and Test-Driving

The system does not read the real wall clock. Instead it maintains a single logical clock that supplies "now" for every time-stamping and time-comparison decision — when a sign was posted, when a sweep completed, when a citation was issued, and how many whole days elapse before payment. At server startup the logical clock reads exactly `2026-03-01T00:00:00Z`; before any client advances it, every read of "now" returns this default rather than real time.

An administrative test-driving capability sets the logical clock to a supplied instant, provided in the `to_iso8601` field of the request body. This capability is available to `PublicWorksAdmin`, `RouteDispatcher`, `SignageInspector`, and `EnforcementOfficer`, and returns no resource payload. All roles except `Resident` may drive the clock.

### 2.6. Optimistic Concurrency Control on Signage

Posting a restriction sign on a block is guarded by optimistic concurrency control. The post-sign operation requires the field `expected_block_version` in its request body, carrying the block `version` the client last observed. Before the sign is superseded, the server compares `expected_block_version` against the block's current `version`. If they do not match — for instance because a prior post-sign already superseded the previous sign and advanced the block's `version` since the client last read it — the request is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412), preventing the client from overwriting signage state it has not observed. This is the only operation in the system that takes a client-supplied version field; no other endpoint accepts or requires one.

### 2.7. Precision, Rounding, and Unit Conversions

Two families of numeric values demand exact treatment.

**Debris tonnage** is derived from integer pound weights. One ton is 2,000 pounds. Every tonnage figure is produced by first summing the relevant integer pound weights, *then* dividing the integer sum by 2,000, *and only then* rounding the quotient half-up to three decimal places. This ordering is fixed and must not be reordered: pounds are summed before any division or rounding occurs. A shift's `total_debris_lbs` is itself the integer sum of pounds (no rounding), and its tonnage fields `gross_tonnage` and `net_tonnage` are the three-decimal, round-half-up conversions of the corresponding pound totals.

**Monetary values** are held as whole integer cents. Citation fines are computed in cents; the only rounding step in the fine formula is a half-up rounding of the multiplier product, applied *before* the statutory cap is imposed (see §3.7). A block's `pending_citation_cents` ledger is likewise an integer-cent total.

### 2.8. Half-Open Time Windows and Overlap Semantics

Several rules reason about time intervals, and they share one convention: an occupation or restriction interval is **half-open**, written `[start, end)` — it includes its start instant and excludes its end instant. Two consequences follow. First, an instant exactly equal to a window's end is *outside* the window. Second, two intervals that merely touch — one ending exactly when the next begins — do *not* overlap; adjacency is permitted.

- A block's posted no-parking window runs from `restriction_start_local` up to but not including `restriction_end_local`, compared as a time-of-day.
- A sweep event's occupation window runs from `window_start_utc` up to but not including `window_end_utc`.
- Two sweep events on the same block may not have overlapping occupation windows when both are in a live state; touching at an endpoint is allowed (see §3.1).
- Shift overlap on the same equipment is evaluated as a **closed** interval expanded by a 30-minute buffer on each side, rather than a half-open one (see §3.3).

### 2.9. Validation Ordering and Referenced-Resource Existence

When several checks could reject a request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and recognized, else `ERR_UNAUTHENTICATED` (401). This is checked on every request.
2. **Authorization** — the acting role must be permitted for the operation per §2.1, else `ERR_UNAUTHORIZED` (403). Checked on every request.
3. **Body validation** — on every creating request, the body must carry all required fields with valid types and enum values, else `ERR_VALIDATION` (422). As part of this step, a suspension whose `scope` is `ROUTE` must supply a `route_id`, and a suspension whose `scope` is `SYSTEM` must omit it; violating either shape yields `ERR_SUSPENSION_SCOPE_INVALID` (422).
4. **Existence** — every resource referenced by a path identifier or a body foreign key must exist, validated left-to-right in the order the identifiers appear. The first missing reference determines the error: `ERR_ROUTE_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_SWEEP_EVENT_NOT_FOUND`, `ERR_SUSPENSION_NOT_FOUND`, `ERR_CITATION_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, or `ERR_COMPLAINT_NOT_FOUND`, each HTTP 404.
5. **Complaint ownership** — a resident acting on a complaint (filing one, or reopening one) must own it, else `ERR_UNAUTHORIZED` (403).
6. **State** — the target resource must be in a state that permits the requested transition, else `ERR_INVALID_STATE` (409). For sweep completion there is an additional cross-entity state check at this same priority: the referenced shift must be `IN_PROGRESS`, else `ERR_SHIFT_NOT_IN_PROGRESS` (409).
7. **Segregation of duties** — on citation adjudication, the acting `X-User-ID` must differ from the citation's `issuing_officer_id`, else `ERR_SEGREGATION_OF_DUTIES` (403).
8. **Signage enforceability** — issuing a citation requires the block's sign to be enforceable and enforcement to be enabled, else `ERR_SIGNAGE_NOT_ENFORCEABLE` (422).
9. **Suspension coverage** — issuing a citation requires that no `ACTIVE` suspension cover the block's route on the scanned date, else `ERR_SWEEP_SUSPENDED` (409).
10. **Restriction window** — the citation's `scanned_at_utc` must fall within the block's half-open restriction window, else `ERR_OUTSIDE_RESTRICTION_WINDOW` (422).
11. **Overlap** — a new sweep event must not overlap a live sweep on the same block (`ERR_SWEEP_OVERLAP`, 409), and a new shift must not overlap an existing shift on the same equipment within the buffer (`ERR_SHIFT_OVERLAP`, 409).
12. **Capacity** — completing a sweep must not push the shift's debris total past the equipment's hopper capacity, else `ERR_SHIFT_CAPACITY_EXCEEDED` (409).
13. **Signage staleness** — the post-sign OCC check of §2.6, else `ERR_STALE_BLOCK_VERSION` (412).

Because the order is strict, a check earlier in the list masks any later one: for example, an unauthenticated request is rejected as `ERR_UNAUTHENTICATED` even if it would also have failed a state check.

### 2.10. Cascading Reconciliation and Derived Ledgers

Several operations mutate more than one entity in a single logical step, and each cascade must land in full. Three derived quantities are maintained incrementally as those cascades fire, and each reconciles exactly to a defining aggregate:

- A route's `completed_block_count` equals the number of sweep events on that route's blocks currently in `SWEPT`. It is incremented by one when a sweep completes and decremented by one when a swept event is voided.
- A shift's `total_debris_lbs` equals the sum of `debris_lbs` over the shift's `SWEPT` sweep events. It rises by the recorded debris on completion and falls by the same amount on void, and its tonnage fields are recomputed each time.
- A block's `pending_citation_cents` equals the sum of `amount_due_cents` over that block's citations whose status is `ISSUED` or `CONTESTED`. It rises when a citation is issued and falls when a citation leaves that pending set (by being upheld, dismissed, or paid).

The most far-reaching cascade is suspension activation, which can suspend many scheduled sweeps at once and, for each suspended sweep, dismiss the citation tied to it — a three-hop chain that ultimately recomputes the affected blocks' pending ledgers. Each such secondary and tertiary effect is specified in §3.6 and §3.7. Whenever any of these reconciliations mutates a resource, that resource's `updated_at` and `version` are refreshed per §2.4.

## 3. Business Logic & Workflows

### 3.1. Routes and the Sweep Calendar

A `RouteDispatcher` establishes a sweeping **route** by supplying its human-readable `name`, the operational `zone_code` the route belongs to (used later to scope suspensions), and the `sweep_weekday` on which it is swept, chosen from `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, or `SUN`. An optional `sweep_ordinal` — an integer from 1 through 5 — narrows the schedule to the Nth occurrence of that weekday in the month; when omitted it defaults to null, meaning every week. A route's `status` may be supplied at creation and is otherwise `ACTIVE`; it is one of `ACTIVE` or `INACTIVE`, where `INACTIVE` routes are retained only for history. Every route also exposes the derived counter `completed_block_count`, which starts at 0 and tracks completed sweeps as described in §2.10.

Individual street segments are modeled as **blocks**, each created by a `RouteDispatcher` against a parent route identified by `route_id`. A block carries a `block_label` such as "100-BLK MAIN ST", a `side` indicating which curb the restriction covers (`ODD`, `EVEN`, or `BOTH`), and the posted window boundaries `restriction_start_local` and `restriction_end_local`, both 24-hour `HH:MM` times of day; `restriction_end_local` must be strictly later than `restriction_start_local`, and the window is interpreted half-open per §2.8. The block's curb length `linear_feet` must be at least 1. A boolean `enforcement_enabled` acts as the master switch for writing citations on the block and defaults to true.

The dispatcher lays out the calendar by scheduling **sweep events**, each tied to a block via `block_id`, with a `scheduled_date` (a `YYYY-MM-DD` calendar date) and an occupation window bounded by `window_start_utc` and `window_end_utc`, where the end must be strictly after the start. A newly scheduled sweep is rejected with `ERR_SWEEP_OVERLAP` if its half-open window overlaps that of another sweep on the same block that is currently `SCHEDULED` or `SWEPT`; two sweeps whose windows merely touch at an endpoint are accepted. A fresh sweep event begins life in `SCHEDULED`. Sweep events may be listed and filtered by block, by shift, by their originating event, or by status.

### 3.2. Posting and Verifying Restriction Signage

Before any block can be enforced, its physical sign must move through a posting-and-verification lifecycle tracked by `sign_status`, which begins at `UNPOSTED` when the block is created. A `SignageInspector` posts a sign by supplying `expected_block_version` (the OCC guard of §2.6) and a `sign_expires_at` expiry timestamp. Posting is permitted from any current signage state: from `UNPOSTED → POSTED` for a first posting, and as a re-post from `POSTED → POSTED` or from `VERIFIED → POSTED`, in every case superseding whatever sign was there before. On a successful post, the server sets `sign_posted_at` to the current logical-clock instant, stores the supplied `sign_expires_at`, sets `sign_status` to `POSTED`, and increments the block's `version` by one. Re-posting from `VERIFIED` deliberately returns the block to `POSTED`, meaning a superseded sign must be re-verified before it can be enforced again.

Verification is a separate step: from `POSTED → VERIFIED`, a `SignageInspector` verifies the posted sign, which sets `sign_status` to `VERIFIED`. Verification is only valid when `sign_status` is currently `POSTED`; attempting it from any other signage state is rejected as an invalid state transition (`ERR_INVALID_STATE`, 409).

Enforceability is a derived property, `sign_enforceable`, that is true exactly when `sign_status` is `VERIFIED` *and* the current logical clock is strictly before `sign_expires_at`. Once the clock reaches or passes `sign_expires_at`, the sign is no longer enforceable even though `sign_status` still reads `VERIFIED`. A block's GET view exposes both `sign_enforceable` and its `pending_citation_cents` ledger.

### 3.3. Sweeper Equipment and Shifts

A `RouteDispatcher` registers a sweeper unit as **equipment**, giving it a fleet `unit_number` (such as "SW-1"), a `type` drawn from `MECHANICAL`, `REGENERATIVE_AIR`, or `VACUUM`, and a `hopper_capacity_lbs` (at least 1) that caps how much debris a single shift on the unit may accumulate. An optional `odometer_miles` reading, which must be a non-negative integer when supplied, defaults to 0. Equipment `status` is system-managed and starts at `AVAILABLE`; it reads `IN_SERVICE` only while a shift on that unit is running.

Work is organized into **shifts**, each created by a dispatcher against a sweeper via `equipment_id`, with an `operator_name`, a `shift_date` (`YYYY-MM-DD`), and UTC bounds `start_utc` and `end_utc` where the end must be after the start. A new shift is rejected with `ERR_SHIFT_OVERLAP` if it collides with another shift on the same equipment; unlike sweep windows, shift collision is evaluated as a *closed* interval expanded by a 30-minute buffer on either end, so two shifts on one unit must be separated by more than 30 minutes to be accepted. A shift begins in `PLANNED`.

Starting a shift advances it `PLANNED → IN_PROGRESS`; it is permitted only when the shift is currently `PLANNED` and its equipment is `AVAILABLE`. As a side effect the equipment transitions `AVAILABLE → IN_SERVICE`. Closing a shift advances it `IN_PROGRESS → CLOSED`, permitted only from `IN_PROGRESS`; closing finalizes the shift's `total_debris_lbs`, `gross_tonnage`, and `net_tonnage`, and returns the equipment `IN_SERVICE → AVAILABLE`. `CLOSED` is terminal for a shift. Both start and close are dispatcher operations, and shifts may be listed and filtered by equipment.

### 3.4. Completing and Voiding Sweeps: Debris and Tonnage

The core field operation is completing a scheduled sweep. A `RouteDispatcher` records a completion against a running shift by supplying that shift's `shift_id` and the `debris_lbs` collected, which must be a non-negative integer. Completion advances the event `SCHEDULED → SWEPT` and is subject to three preconditions evaluated in the order of §2.9: the event must currently be `SCHEDULED` (else `ERR_INVALID_STATE`), the referenced shift must exist and be `IN_PROGRESS` (else `ERR_SHIFT_NOT_IN_PROGRESS`), and the sum of the shift's current `total_debris_lbs` plus the incoming `debris_lbs` must not exceed the equipment's `hopper_capacity_lbs`. That capacity comparison is strict: any total that would exceed the hopper capacity is rejected with `ERR_SHIFT_CAPACITY_EXCEEDED`, while a total exactly equal to the capacity is allowed.

On a successful completion the server sets the event's `status` to `SWEPT`, records `debris_lbs`, stamps `completed_at` with the current logical-clock instant, and writes the `shift_id`. It then adds the recorded pounds to the shift's `total_debris_lbs` and recomputes the shift's `gross_tonnage` and `net_tonnage`, and increments the parent route's `completed_block_count` by one.

The two tonnage figures differ in how they treat re-sweeps of the same block within a shift. **Gross** counts every `SWEPT` event: `gross_lbs` is the sum of `debris_lbs` over all of the shift's `SWEPT` events, and `gross_tonnage` is that integer sum divided by 2,000 pounds per ton, rounded half-up to three decimals; `total_debris_lbs` is exactly `gross_lbs`. **Net** de-duplicates re-sweeps down to one event per block: for each distinct block that has any `SWEPT` event on the shift, the winning event is the one with the greatest `completed_at`, breaking ties in favor of the greatest `created_at`; `net_lbs` is the sum of the winners' `debris_lbs`, and `net_tonnage` is that sum divided by 2,000 and rounded half-up to three decimals. Only `SWEPT` events with the matching shift are counted; `VOIDED`, `MISSED`, and `SUSPENDED` events are excluded from both figures. As required by §2.7, pounds are summed first, divided second, and rounded last.

A completed sweep can be corrected. Voiding a swept event advances it `SWEPT → VOIDED`, permitted only from `SWEPT`; it subtracts that event's `debris_lbs` back out of the shift's `total_debris_lbs`, recomputes the shift's `gross_tonnage` and `net_tonnage`, and decrements the route's `completed_block_count` by one. `VOIDED` is terminal for a sweep event. An optional free-text `reason` may accompany the void.

### 3.5. Missed Sweeps and Automatic Makeups

When a scheduled sweep cannot be performed, a `RouteDispatcher` marks it missed, optionally noting a `reason`. Missing advances the event `SCHEDULED → MISSED` (permitted only from `SCHEDULED`). As a side effect the system automatically creates a **makeup** sweep event for the same block: the new event has `is_makeup` set to true, its `original_event_id` pointing back to the missed event, the same `block_id`, a `status` of `SCHEDULED`, and a `scheduled_date` set to the calendar date of the current logical clock advanced by the fixed makeup offset of **7 calendar days** (the `MAKEUP_OFFSET_DAYS` constant, whose value is 7). The makeup event's `window_start_utc` and `window_end_utc` are the missed event's window timestamps shifted forward by the same 7-day offset. The `is_makeup` flag is false and `original_event_id` is null for all ordinary (non-makeup) events. Makeup events can be located by filtering sweep events on their originating event.

### 3.6. Seasonal Suspensions: Holidays and Leaf Season

A `PublicWorksAdmin` declares a **suspension** to pause sweeping for a holiday, the leaf-fall season, weather, or another cause — the `reason` is one of `HOLIDAY`, `LEAF_SEASON`, `WEATHER`, or `OTHER`. The `scope` is either `SYSTEM`, which pauses all routes, or `ROUTE`, which pauses a single route. When `scope` is `ROUTE` a `route_id` is required, and when `scope` is `SYSTEM` a `route_id` must not be supplied; violating this shape is rejected with `ERR_SUSPENSION_SCOPE_INVALID`. The suspended span runs from `start_date` through `end_date` inclusive, and `end_date` must be on or after `start_date`. A suspension is created in `SCHEDULED` and exposes a `suspended_event_count` that starts at 0.

Activating a suspension advances it `SCHEDULED → ACTIVE` (permitted only from `SCHEDULED`) and drives the system's largest cascade. For every sweep event that is currently `SCHEDULED`, whose `scheduled_date` falls on or between the suspension's `start_date` and `end_date`, and that is in scope — meaning the suspension is `SYSTEM`-scoped, or the event's block belongs to the suspension's `route_id` — the event is transitioned `SCHEDULED → SUSPENDED`. The count of events moved this way is written to `suspended_event_count`. This is the first hop. As the second hop, each newly suspended event dismisses any citation tied to it: for every citation whose `sweep_event_id` equals the suspended event and whose status is `ISSUED`, the citation transitions `ISSUED → DISMISSED`. As the third hop, each such dismissal subtracts that citation's `amount_due_cents` from its block's `pending_citation_cents`, per §2.10.

Lifting an active suspension advances it `ACTIVE → LIFTED` (permitted only from `ACTIVE`). Lifting is deliberately non-restorative: events that were moved to `SUSPENDED` are *not* automatically rescheduled, and a dispatcher must reschedule them manually. `LIFTED` is terminal. Suspensions may be listed and filtered by route or status.

### 3.7. LPR Citations: Issuance, Contest, Adjudication, and Payment

An `EnforcementOfficer` issues a citation when the license-plate reader observes a `plate` on a block during its restriction window. Issuance takes the `block_id`, the `plate`, and the LPR read timestamp `scanned_at_utc`, plus an optional `sweep_event_id` tying the citation to a particular scheduled sweep. Three business gates apply, in the priority order of §2.9. First, the block's sign must be enforceable and enforcement enabled — that is, `sign_enforceable` must be true (VERIFIED and unexpired per §3.2) and `enforcement_enabled` must be true — else `ERR_SIGNAGE_NOT_ENFORCEABLE`. Second, no `ACTIVE` suspension may cover the block's route on the scanned date, else `ERR_SWEEP_SUSPENDED`. Third, the time-of-day of `scanned_at_utc` must fall within the block's half-open restriction window `[restriction_start_local, restriction_end_local)`, else `ERR_OUTSIDE_RESTRICTION_WINDOW`.

On issuance the citation is created in `ISSUED`, its `issued_at` stamped with the current logical clock, and its `issuing_officer_id` set to the acting officer's `X-User-ID`. The system computes the derived `prior_upheld_count` — the number of earlier citations for the same `plate` whose status is `UPHELD` or `PAID`, counting only citations created before this one and excluding the citation itself — and pins the provisional fine into `amount_due_cents`. Issuing the citation also adds `amount_due_cents` to the block's `pending_citation_cents`.

The fine is a tiered computation in integer cents. It begins from a base fine of 6,000 cents (`BASE_FINE_CENTS`, i.e. $60.00) plus a late-fee component `late_fee_cents`. The late fee is 0 when the days-late count is zero or less; 1,500 cents ($15.00) when the citation is between 1 and 15 whole days late; 3,000 cents ($30.00) when between 16 and 30 days late; and 5,000 cents ($50.00) when more than 30 days late. The sum of base and late fee is then multiplied by a repeat-offender multiplier driven by `prior_upheld_count`: the multiplier is 1.0 when there are no prior upheld/paid citations, 1.5 when there are 1 or 2, and 2.0 when there are 3 or more. That product is rounded half-up to whole cents, and finally the result is capped at 20,000 cents (`FINE_CAP_CENTS`, $200.00) — the smaller of the rounded product and the cap is the fine. Note the rounding happens on the multiplier product *before* the cap is applied.

The fine has two variants. The **provisional** fine is computed at issuance and stored in `amount_due_cents`: because a freshly issued citation has a `days_late` pinned to 0, its `late_fee_cents` is 0 and only the base and repeat multiplier apply. The **final** fine is computed at payment and stored in `paid_amount_cents`: at that point `days_late` is set to the number of whole days from `issued_at` to the payment-time logical clock, the applicable late-fee tier is folded in, and the multiplier and cap are applied as above. The `days_late` field is null while a citation is unsettled and is populated only at settlement; `paid_amount_cents` is null until the citation is `PAID`.

A citation's life after issuance branches. Contesting advances it `ISSUED → CONTESTED` (permitted only from `ISSUED`); it may carry an optional `reason`. A contested citation remains inside the pending-ledger set `{ISSUED, CONTESTED}`, so `pending_citation_cents` is unchanged by a contest. Adjudication resolves a contested citation and requires the `decision` field, which is either `UPHOLD` or `DISMISS`; it is permitted only from `CONTESTED` and only when the acting `X-User-ID` differs from the citation's `issuing_officer_id` (segregation of duties, `ERR_SEGREGATION_OF_DUTIES`). Upholding advances the citation `CONTESTED → UPHELD`, records the acting officer's `X-User-ID` in `adjudicator_id`, and subtracts `amount_due_cents` from the block's `pending_citation_cents` as it leaves the pending set. Dismissing advances the citation `CONTESTED → DISMISSED`, likewise records `adjudicator_id`, and subtracts `amount_due_cents` from the block's ledger to compensate the original issuance debit. `adjudicator_id` is null until adjudication.

A citation may also be dismissed by the suspension cascade of §3.6: from `ISSUED → DISMISSED`, driven by the system when the event named in the citation's `sweep_event_id` is suspended, again subtracting `amount_due_cents` from the block's pending ledger. Payment can be made from two starting states: `ISSUED → PAID` for a citation that was never contested, and `UPHELD → PAID` for one whose contest was upheld. In both cases the server sets `days_late`, computes `paid_amount_cents` via the final fine variant, and moves the citation to `PAID`. Paying an `ISSUED` citation removes its provisional debit by subtracting `amount_due_cents` from `pending_citation_cents`; paying an `UPHELD` citation makes no further ledger adjustment because the upholding step already removed it from the pending set. Both `DISMISSED` and `PAID` are terminal. Citations may be listed and filtered by block, sweep event, plate, or status.

### 3.8. Residents, Notifications, and Complaints

A `RouteDispatcher` registers a **resident** by supplying the resident's `email`, `full_name`, and `home_block_id` (the block the resident lives on, targeted by notifications). A `notify_opt_in` boolean governs whether the resident receives sweep notifications and defaults to true. Residents may be listed and filtered by home block.

Notifications are dispatched per sweep event. A dispatcher triggers a notification run on a scheduled sweep, optionally naming a `channel`; the run is permitted regardless of the event's current status (no state precondition applies) and sets the event's `notified_resident_count` to the number of opted-in residents on that event's block. This counter defaults to 0 before any notification run.

Residents raise **complaints**, each filed by the owning resident with `resident_id` (which must equal the caller's `X-User-ID`), the `block_id` the complaint concerns, and a `category` of `MISSED_BLOCK`, `DEBRIS_LEFT`, `SIGN_DAMAGED`, or `OTHER`. An optional `linked_sweep_event_id` references a specific sweep event. A complaint opens in `OPEN`. A `RouteDispatcher` dispositions it: resolving advances an open complaint `OPEN → RESOLVED` and records the supplied `resolution_note`, while rejecting advances it `OPEN → REJECTED` and likewise records a `resolution_note`. `REJECTED` is terminal. The owning resident may reopen a resolved complaint, advancing it `RESOLVED → REOPENED` (permitted only from `RESOLVED`, and only when the caller's `X-User-ID` equals the complaint's `resident_id`); an optional `reason` may accompany the reopen. A reopened complaint can be resolved again by a dispatcher, advancing it `REOPENED → RESOLVED` with a fresh `resolution_note`. The full revision cycle is therefore `OPEN → RESOLVED → REOPENED → RESOLVED`. Complaints may be listed and filtered by resident, block, linked sweep event, or status.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — every state transition, sign posting, cascade trigger, and the logical-clock control — return `200 OK`. All read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/routes` | Create a sweeping route | RouteDispatcher |
| GET | `/api/routes/{id}` | Fetch a route (includes completed_block_count) | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| POST | `/api/blocks` | Create a block on a route | RouteDispatcher |
| GET | `/api/blocks/{id}` | Fetch a block (includes sign_enforceable, pending_citation_cents) | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| GET | `/api/blocks` | List blocks, optionally filtered by route | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| POST | `/api/blocks/{id}/post-sign` | Post or re-post a restriction sign; OCC-guarded on block version | SignageInspector |
| POST | `/api/blocks/{id}/verify-sign` | Verify a posted sign, enabling enforcement | SignageInspector |
| POST | `/api/equipment` | Register a sweeper unit | RouteDispatcher |
| GET | `/api/equipment/{id}` | Fetch a sweeper unit | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| POST | `/api/shifts` | Schedule a shift on a sweeper unit | RouteDispatcher |
| GET | `/api/shifts/{id}` | Fetch a shift (includes total_debris_lbs, gross_tonnage, net_tonnage) | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| GET | `/api/shifts` | List shifts, optionally filtered by equipment | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| POST | `/api/shifts/{id}/start` | Start a shift (equipment → IN_SERVICE) | RouteDispatcher |
| POST | `/api/shifts/{id}/close` | Close a shift and finalize tonnage (equipment → AVAILABLE) | RouteDispatcher |
| POST | `/api/sweep-events` | Schedule a sweep occurrence for a block | RouteDispatcher |
| GET | `/api/sweep-events/{id}` | Fetch a sweep event | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| GET | `/api/sweep-events` | List sweep events by block, shift, original event, or status | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| POST | `/api/sweep-events/{id}/complete` | Record a completed sweep with debris weight against a running shift | RouteDispatcher |
| POST | `/api/sweep-events/{id}/miss` | Mark a sweep missed; auto-creates a makeup event | RouteDispatcher |
| POST | `/api/sweep-events/{id}/void` | Void a completed sweep; reverses debris and coverage | RouteDispatcher |
| POST | `/api/sweep-events/{id}/notify` | Dispatch sweep notifications to opted-in residents on the block | RouteDispatcher |
| POST | `/api/suspensions` | Create a holiday/leaf-season suspension window | PublicWorksAdmin |
| GET | `/api/suspensions/{id}` | Fetch a suspension | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| GET | `/api/suspensions` | List suspensions by route or status | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| POST | `/api/suspensions/{id}/activate` | Activate a suspension; cascades to suspend sweeps and dismiss tied citations | PublicWorksAdmin |
| POST | `/api/suspensions/{id}/lift` | Lift an active suspension | PublicWorksAdmin |
| POST | `/api/citations` | Issue an LPR citation for a plate observed during a restriction window | EnforcementOfficer |
| GET | `/api/citations/{id}` | Fetch a citation | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| GET | `/api/citations` | List citations by block, sweep event, plate, or status | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| POST | `/api/citations/{id}/contest` | Contest an issued citation | EnforcementOfficer |
| POST | `/api/citations/{id}/adjudicate` | Adjudicate a contested citation (uphold or dismiss); segregation of duties enforced | EnforcementOfficer |
| POST | `/api/citations/{id}/pay` | Pay a citation; computes the final fine with any late-fee tier | EnforcementOfficer |
| POST | `/api/residents` | Register a resident on a block | RouteDispatcher |
| GET | `/api/residents/{id}` | Fetch a resident | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| GET | `/api/residents` | List residents, optionally filtered by home block | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| POST | `/api/complaints` | File a complaint (resident owner) | Resident |
| GET | `/api/complaints/{id}` | Fetch a complaint | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| GET | `/api/complaints` | List complaints by resident, block, linked sweep event, or status | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer, Resident |
| POST | `/api/complaints/{id}/resolve` | Resolve an open or reopened complaint | RouteDispatcher |
| POST | `/api/complaints/{id}/reject` | Reject an open complaint | RouteDispatcher |
| POST | `/api/complaints/{id}/reopen` | Reopen a resolved complaint (resident owner) | Resident |
| POST | `/_clock/set_current_utc` | Set the logical clock | PublicWorksAdmin, RouteDispatcher, SignageInspector, EnforcementOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_SUSPENSION_SCOPE_INVALID` | 422 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_BLOCK_NOT_FOUND` | 404 |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_SWEEP_EVENT_NOT_FOUND` | 404 |
| `ERR_SUSPENSION_NOT_FOUND` | 404 |
| `ERR_CITATION_NOT_FOUND` | 404 |
| `ERR_RESIDENT_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SHIFT_NOT_IN_PROGRESS` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SIGNAGE_NOT_ENFORCEABLE` | 422 |
| `ERR_SWEEP_SUSPENDED` | 409 |
| `ERR_OUTSIDE_RESTRICTION_WINDOW` | 422 |
| `ERR_SWEEP_OVERLAP` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_SHIFT_CAPACITY_EXCEEDED` | 409 |
| `ERR_STALE_BLOCK_VERSION` | 412 |
