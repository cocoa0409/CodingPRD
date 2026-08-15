# Water Main Break Response API — Product Requirements Document

## 1. Introduction

A municipal water department lives and dies by how quickly it can convert the first sign of a distribution failure — a frantic customer call about water bubbling up through pavement, a SCADA pressure-drop alert, a field crew's radio report — into an isolated, repaired, restored, and financially closed incident. Today those steps live in disconnected spreadsheets and radio logs: isolation plans are drawn by hand, outage extents are estimated by gut feel, boil-water advisories are issued and lifted without a defensible sampling record, and property-damage claims arrive months later with no clean link back to the break that caused them. This document specifies a single API that owns the entire lifecycle of a water main break, from intake through closure, for the department's dispatchers, field crews, water-quality officers, claims adjusters, and city engineers.

The system tracks the water distribution network as a registry of pipe segments and the valves that serve them. When a break is reported, dispatch triage-confirms it against a specific segment, correlates it with SCADA pressure or flow anomalies, and plans a valve isolation that computes exactly how many customers are out of service — large outages automatically trigger a boil-water advisory. Repair work orders are sized for materials and crew class, dispatched under strict crew-availability rules, and completed with actual costs that roll up into a per-break fiscal ledger alongside street-restoration costs and settled damage claims. Restoration jobs run against approved traffic permits under hard deadlines, and a periodic operations checkpoint expires permits, flags overdue restorations, and re-derives each segment's repeat-break posture so that chronic segments surface as replacement candidates.

Because public-health and public-money decisions are involved, the system enforces segregation of duties (the officer who issues an advisory cannot lift it), optimistic concurrency on break-level planning, and a logical clock so that every deadline — the 90-day claim filing window, the 14-day restoration deadline, the 36-month repeat-break window — is evaluated deterministically rather than against wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 400) before any other processing. If the named role is not in the endpoint's authorized role list — or, for the crew-ownership actions described in §3.4, the calling user's identity does not match the work order's assigned crew — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Six roles are recognized, spelled exactly as follows:

- `Dispatcher` — water department dispatcher: intake, triage, isolation planning and execution, crew and restoration scheduling, permit applications, claim intake.
- `CrewLead` — field crew leader.
- `WaterQualityOfficer` — water quality compliance officer; issues and lifts boil-water advisories and records samples.
- `ClaimsAdjuster` — claims office adjuster; decides and settles property-damage claims.
- `PublicWorksEngineer` — city engineer; registers assets, approves traffic permits, programs replacement, closes breaks.
- `System` — machine account: SCADA anomaly feed, logical clock, and the operations checkpoint.

Identity semantics differ by role. When `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the acting `Crew`; ownership checks on the crew-ownership actions compare the work order's `crew_id` field to `X-User-ID`. When `X-User-Role` is `Dispatcher`, `WaterQualityOfficer`, `ClaimsAdjuster`, `PublicWorksEngineer`, or `System`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `issued_by_user_id` or `lifted_by_user_id` on a boil-water advisory) but does not compare it to any entity's `id`.

All six roles may call every GET endpoint. Mutating endpoints are restricted per the endpoint table in §4.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's real UTC wall clock rather than the logical clock.
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

Requests that match no defined route — or an unsupported method on a defined route — are rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope, and unexpected internal failures surface as `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints accept two optional query parameters: `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Non-integer or unparseable `limit`/`offset` values fall back to these defaults, and out-of-range values are clamped to the stated bounds rather than rejected. List responses are sorted by `created_at` ascending, with ties broken by registration order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` in addition to the standard request metadata.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version` that starts at 1. Both timestamps are ISO 8601 UTC with three fractional digits. Every timestamp the server returns uses this same canonical form — ISO 8601 UTC with exactly three fractional digits and a `Z` suffix — including instants that originated in client requests (for example `observed_at`, `sampled_at`, `last_sample_at`, `valid_from`, `valid_to`, `scheduled_start`, and `scheduled_end`). Client-supplied instants are parsed as ISO 8601, normalized to UTC (instants without an offset are interpreted as UTC), and re-rendered canonically rather than echoed verbatim, so a `sampled_at` submitted as `2026-08-02T00:00:00Z` is returned as `2026-08-02T00:00:00.000Z`. `updated_at` is refreshed and `version` is incremented by exactly 1 on every mutation of the resource, including mutations caused by system cascades (for example, when confirming a break bumps the break's `version`, or when an isolation execution closes valves).

All deadlines, windows, and time-ordered comparisons in this system are evaluated against a **logical clock**, never wall-clock time. At server startup, before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z. A `System`-role capability sets the logical clock to a supplied `to_iso8601` instant — forward or backward, with no monotonicity constraint — and responds with the new reading as `current_utc` in canonical form; the server never falls back to wall-clock time on its own. Timestamps described throughout this document as "clock now" refer to the logical clock at the moment of the operation.

### 2.5. Nested Resource Retrieval and Existence Checking

Resource references are validated left to right. When a request references a resource by id — whether in the URL path or in the request body — each referenced id must exist; the first missing reference is rejected with `ERR_NOT_FOUND` (HTTP 404). For nested listing routes (for example, listing the valves that serve a segment, or the work orders of a break), the parent id in the path is validated before the listing is produced. Malformed fields, invalid enum values, non-positive quantities where a positive value is required, and windows whose start is not before their end are rejected with `ERR_VALIDATION` (HTTP 400) at the same tier as existence checking.

### 2.6. Optimistic Concurrency Control on Break-Level Planning

Exactly one write operation in this API is guarded by optimistic concurrency control: the creation of a valve isolation plan. That request must carry `expected_break_report_version`, set to the `version` of the parent break report the client last observed; a missing or non-integer value is rejected with `ERR_VALIDATION` (HTTP 400) before the staleness comparison. If the value does not equal the break report's current `version` at the moment of creation, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because creating an isolation plan legitimately advances the break report's `version` (see §3.3), a client holding a pre-supersede version is told its view is stale rather than being allowed to silently supersede a plan it never saw. No other endpoint takes a version field.

### 2.7. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed order so that the surfaced error is deterministic. Header presence comes first (`ERR_MISSING_CONTEXT_HEADER`), then role authorization and crew ownership (`ERR_FORBIDDEN_ROLE`), then existence and basic field validity (`ERR_NOT_FOUND`, `ERR_VALIDATION`), then the optimistic-concurrency check on isolation-plan creation (`ERR_STALE_VERSION`), then source-state legality for the requested transition (`ERR_INVALID_STATE`, with a permit that is not yet approved at restoration scheduling surfacing at this same tier as `ERR_PERMIT_NOT_APPROVED`). After state legality come the domain guard tiers: water-quality compliance (`ERR_ADVISORY_TESTS_INSUFFICIENT`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_TEST_SAMPLE_TOO_SOON`), cross-aggregate referential integrity (`ERR_CROSS_REFERENCE_MISMATCH`, `ERR_SEGMENT_REPLACED`), temporal windows (`ERR_CLAIM_FILED_LATE`, `ERR_PERMIT_WINDOW_MISMATCH`, `ERR_PERMIT_OVERLAP`, `ERR_CREW_DOUBLE_BOOKED`, `ERR_CORRELATION_WINDOW`), structural constraints (`ERR_BREAK_NOT_ISOLATED`, `ERR_DUPLICATE_ACTIVE_WORK_ORDER`, `ERR_ADVISORY_ALREADY_OPEN`, `ERR_ADVISORY_STILL_ACTIVE`, `ERR_CLAIMS_OPEN`, `ERR_NO_CREW_AVAILABLE`), and finally fiscal rules (`ERR_INVALID_AMOUNT` with HTTP 400, and `ERR_AMOUNT_EXCEEDS_CLAIMED` with HTTP 409).

### 2.8. Money, Precision, and Rounding

All monetary values are integer cents. Where a calculation produces a fractional cent, it is rounded half-up to a whole cent. Two rounding disciplines appear in this system and must not be conflated: the forward-looking repair estimate applies a single round-half-up after the length-times-rate-times-multiplier product, while the chronological actual-cost calculation rounds each materials line individually before summing (see §3.4 and §3.6). Water chlorine residuals are recorded in milligrams per liter and compared against a threshold of 0.20 with an inclusive boundary.

### 2.9. Status Codes

Creating a new resource returns HTTP 201. Actions that modify an existing resource in place — confirmations, dispatches, arrivals, completions, approvals, payments, scheduling, lifting, closing — return HTTP 200. Reads return HTTP 200.

## 3. Business Logic & Workflows

### 3.1. Asset Registry: Pipe Segments, Valves, and SCADA Anomalies

The network model begins with the pipe segment. A `PublicWorksEngineer` registers a segment with its human-readable `segment_ref` (a unique code such as MAIN-12-OAK), its `material` (one of `CAST_IRON`, `DUCTILE_IRON`, `PVC`, `AC`, or `STEEL`), its nominal `diameter_inches` (an integer of at least 1), and its `install_year` (an integer). A duplicate `segment_ref` is rejected with `ERR_VALIDATION` (HTTP 400). A new segment's `condition_status` starts at `NONE`, both of its repeat-break counters (`repeat_break_count_36mo` and `provisional_break_count_36mo`) start at 0, and `replaced_at` is null. The diameter recorded here later drives both crew-class requirements and clamp-kit sizing for every repair on the segment, so it is a sizing input, not a descriptive label.

Valves are registered per segment by a `PublicWorksEngineer` as well. Each valve carries a unique `valve_code`, the `pipe_segment_id` of the segment it serves, a `coverage_zone` label, and a `customers_served` count that must be greater than zero. A duplicate `valve_code` is rejected with `ERR_VALIDATION` (HTTP 400). The coverage zone matters because valves sharing a zone protect overlapping customer sets; the outage-extent computation in §3.3 deduplicates by zone rather than summing raw customer counts. A valve is born with `valve_status` `OPEN` and moves between `OPEN` and `CLOSED` only as a side effect of isolation execution and restoration — there is no direct valve-mutation endpoint.

The `System` role feeds the registry's observability side by posting pressure and flow anomaly observations against a segment. Each observation names the `pipe_segment_id`, an `anomaly_type` of `PRESSURE_DROP` or `FLOW_SPIKE`, the `observed_at` instant in the logical-clock domain, and a `magnitude_pct` integer deviation between 1 and 100 percent, inclusive. Every anomaly is born with `correlation_status` `UNCORRELATED` and a null `correlated_break_report_id`; the correlation workflow in §3.2 is the only way those fields change. The valves serving a segment and the anomalies observed on a segment are both listable under the segment's own nested routes, as are the break reports confirmed against it.

### 3.2. Break Intake, Triage, and Anomaly Correlation

A break enters the system when a `Dispatcher` files a report with a free-text `location_description` and a `source` of `CUSTOMER_CALL`, `SENSOR_SCADA`, or `CREW_OBSERVATION`. The report is born with `break_status` `REPORTED`, no assigned segment, no `break_type`, no `severity`, and both `confirmed_at` and `repaired_at` null. All of its fiscal rollups (`total_repair_cost_cents`, `total_restoration_cost_cents`, `claims_liability_cents`, `total_claims_paid_cents`, `total_cost_cents`) start at 0, and `customers_out_of_service` starts at 0.

Triage confirmation is the pivot point of the whole workflow. A `Dispatcher` confirms a `REPORTED` report by supplying the `pipe_segment_id` it occurred on, the `break_type` (`CIRCUMFERENTIAL`, `SPLIT`, or `BLOWOUT`), and the `severity` (`LOW`, `MEDIUM`, or `HIGH`). Confirmation moves the report from `REPORTED` to `CONFIRMED`, stamps `confirmed_at` with the logical-clock now, records the three supplied attributes, increments the report's `version`, and immediately recomputes both of the segment's repeat-break counts against the current logical clock — the newly confirmed break itself contributes only to the provisional count until it reaches a completed state, and the segment's condition posture is re-derived only at the operations checkpoint (see §3.8). Confirmation against a segment whose `condition_status` is `REPLACED` is rejected with `ERR_SEGMENT_REPLACED`, because a replaced main cannot legitimately break again. If the report turns out to be unfounded, the `Dispatcher` instead marks it a false alarm, moving `REPORTED` to `FALSE_ALARM`; a false alarm is terminal and excluded from every count and every downstream workflow.

Once a report is `CONFIRMED`, a `Dispatcher` may correlate a pressure or flow anomaly to it by submitting the `pressure_anomaly_id`. Four conditions guard this linkage, all checked at correlation time: the break must still be `CONFIRMED` (otherwise `ERR_INVALID_STATE`); the anomaly must still be `UNCORRELATED` (otherwise `ERR_INVALID_STATE`); the anomaly's `pipe_segment_id` must equal the break's `pipe_segment_id` (otherwise `ERR_CROSS_REFERENCE_MISMATCH`); and the absolute difference between the anomaly's `observed_at` and the break report's `created_at` must be no more than six hours (otherwise `ERR_CORRELATION_WINDOW`). A successful correlation stamps the anomaly's `correlated_break_report_id` with the break's id and flips its `correlation_status` to `CORRELATED`. The anomalies correlated to a break are listable under the break's nested route.

### 3.3. Valve Isolation: Planning, Supersession, and Execution

With a break `CONFIRMED`, the `Dispatcher` plans a valve isolation by naming the `break_report_id` and a non-empty `valve_ids` list. At planning time the list is validated only as a non-empty array of non-empty id strings; each valve's existence, its service of the break's segment, and its `OPEN` status are checked only at execution. This is the OCC-guarded creation described in §2.6: the request must carry `expected_break_report_version` equal to the break's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The parent break must be in `CONFIRMED` or `REPAIRED` status — the latter covers rework re-isolation after a failed repair — and any other state yields `ERR_INVALID_STATE`. Creating a new plan for a break supersedes any prior plan still in `PLANNED` status for that same break (the older plan's `isolation_status` becomes `SUPERSEDED`), and the creation itself increments the break's `version`, which is exactly why the OCC check exists. A new plan is born `PLANNED` with `outage_extent_customers`, `executed_at`, and `restored_at` all null. The plans of a break are listable under the break's nested route.

Execution is the moment the plan bites. A `Dispatcher` executes a `PLANNED` plan; the parent break must still be `CONFIRMED` or `REPAIRED` at that moment (otherwise `ERR_INVALID_STATE`), duplicate ids in `valve_ids` are deduplicated before any checks, and every valve in its `valve_ids` must exist, must serve the break's `pipe_segment_id` (a valve from another segment yields `ERR_CROSS_REFERENCE_MISMATCH`), and must currently be `OPEN` (otherwise `ERR_INVALID_STATE`). On execution all listed valves flip to `CLOSED`, `executed_at` is stamped, and the outage extent is computed by zone deduplication: the closed valves are grouped by `coverage_zone`, and `outage_extent_customers` is the sum over distinct zones of the largest `customers_served` among the closed valves in that zone — the largest valve in a zone is taken to cover the others' customers. The computed extent is copied onto the break's `customers_out_of_service`, and the break itself moves from `CONFIRMED` (or `REPAIRED`, in the rework loop) to `ISOLATED`.

The outage extent has a public-health consequence. If `outage_extent_customers` is at least 500 — the boundary is inclusive, so exactly 500 triggers and 499 does not — and no advisory in `ISSUED` status already exists for the break, the system automatically creates a boil-water advisory with `issue_reason` `AUTO_OUTAGE_THRESHOLD`, `advisory_status` `ISSUED`, `issued_by_user_id` set to the literal string "system", and `issued_at` stamped with the clock now. On a rework re-isolation (`REPAIRED` back to `ISOLATED`), the same threshold rule fires but only when no `ISSUED` advisory currently exists.

When a repair completes (§3.4), the executed plan for the break is restored: `isolation_status` moves from `EXECUTED` to `RESTORED`, every listed valve returns to `OPEN`, `restored_at` is stamped, and the break's `customers_out_of_service` returns to 0.

### 3.4. Repair Work Orders: Sizing, Dispatch, Arrival, Completion

A `Dispatcher` opens a repair work order against a break by supplying the `break_report_id` and an `est_pipe_length_ft` — the estimated length of pipe to be replaced, which must be an integer greater than zero. The break must be in `CONFIRMED`, `ISOLATED`, or `REPAIRED` status (otherwise `ERR_INVALID_STATE`), and a break may have at most one work order in any of `DRAFT`, `DISPATCHED`, or `ON_SITE` at a time; a second attempt is rejected with `ERR_DUPLICATE_ACTIVE_WORK_ORDER`. Work orders are listable both globally — filterable by `break_report_id` and/or `crew_id`, with both supplied filters applying together — and under the break's nested route.

Material sizing is derived at creation. The required equipment class is `HEAVY` when the segment's `diameter_inches` is greater than 12 or the break's `break_type` is `BLOWOUT`, and `LIGHT` otherwise; this is recorded on the work order as `required_equipment_class`. The clamp kit is tiered by diameter: `CLAMP_A` when `diameter_inches` is less than 8, `CLAMP_B` when it is from 8 up to and including 16, and `CLAMP_C` when it is greater than 16 — recorded as `required_clamp_kit`. The new work order's `work_status` is born `DRAFT` with `crew_id` null, both dispatch window bounds null, and `estimated_cost_cents`, `actual_cost_cents`, and `cost_variance_cents` all null.

Dispatch turns a draft into field work. A `Dispatcher` dispatches a `DRAFT` work order, optionally naming a `crew_id`; the parent break must be `ISOLATED` at that moment, otherwise `ERR_BREAK_NOT_ISOLATED`. If a crew is named explicitly it must satisfy the eligibility rules below; if `crew_id` is omitted, the deterministic selector runs. Eligibility requires `crew_status` `AVAILABLE`, an equipment class sufficient for the job (any class suffices when `required_equipment_class` is `LIGHT`; a `HEAVY` requirement demands a `HEAVY` crew), and no overlapping occupied window. A crew's occupied window runs from an existing dispatched-or-on-site work order's `dispatch_window_start` through its `dispatch_window_end` plus a 60-minute travel buffer: a new dispatch at clock time T is rejected with `ERR_CREW_DOUBLE_BOOKED` when T falls at or after `dispatch_window_start` and strictly before `dispatch_window_end` plus 60 minutes; at T exactly equal to `dispatch_window_end` plus 60 minutes the occupied window no longer overlaps, so the window rule by itself does not reject. The boundary relaxes only the window condition, never the `crew_status` condition: a crew's `crew_status` does not change with the passage of time and remains `DISPATCHED` until the occupying work order is completed or cancelled, so while that order is still `DISPATCHED` or `ON_SITE` the crew fails the `crew_status` `AVAILABLE` requirement at every T — T exactly at the window boundary included — and a dispatch that names such a crew is rejected with `ERR_CREW_DOUBLE_BOOKED`. When the selector runs, eligible crews are ranked by `completed_job_count` ascending and then by `created_at` ascending, so the least-experienced eligible crew — earliest-registered on ties — wins; an empty pool yields `ERR_NO_CREW_AVAILABLE`. Crew ids are never used for ranking or tie-breaking.

A successful dispatch moves the work order from `DRAFT` to `DISPATCHED`, assigns `crew_id`, flips the crew to `DISPATCHED`, stamps `dispatch_window_start` with the clock now, and sets `dispatch_window_end` to the start plus an estimated duration of 4 hours for a `CIRCUMFERENTIAL` break, 6 hours for a `SPLIT`, or 10 hours for a `BLOWOUT`. Dispatch also computes `estimated_cost_cents`, the forward-looking cost variant: take the `est_pipe_length_ft`, multiply it by a per-foot rate of 12000 cents when the diameter is less than 8 inches, 18000 cents when the diameter is from 8 up to and including 16 inches, or 25000 cents when greater than 16, then multiply that product by a break-type multiplier of 1.0 for `CIRCUMFERENTIAL`, 1.25 for `SPLIT`, or 1.6 for `BLOWOUT`, and round the result half-up to whole cents; add a clamp-kit fee of 40000 cents for `CIRCUMFERENTIAL`, 85000 for `SPLIT`, or 150000 for `BLOWOUT`; and add the assigned crew's `hourly_rate_cents` multiplied by the estimated hours from the break-type table above.

Arrival and completion belong to the field. A `CrewLead` marks arrival, moving the work order from `DISPATCHED` to `ON_SITE`; the acting user's `X-User-ID` must equal the work order's `crew_id` (otherwise `ERR_FORBIDDEN_ROLE`). Arrival cascades the break from `ISOLATED` to `IN_REPAIR` — on rework, the break re-enters `IN_REPAIR` only after a fresh isolation has moved it `REPAIRED` → `ISOLATED` first.

Completion is the richest cascade in the system. A `CrewLead` completes an `ON_SITE` work order (again ownership-checked against `crew_id`) by logging `actual_pipe_length_ft`, `labor_hours`, and `materials_used` — a list of line items each carrying a `quantity` and a `unit_price_cents`. `actual_pipe_length_ft` must be a number greater than zero and `labor_hours` a number at or above zero; `materials_used` must be a list — an empty list is allowed and contributes nothing — and each line's `quantity` must be a positive number and its `unit_price_cents` a non-negative integer. The chronological actual-cost variant computes `actual_cost_cents` as follows: labor is `labor_hours` multiplied by the crew's `hourly_rate_cents`, rounded half-up to whole cents; each materials line is rounded individually before any summing, as `quantity` times `unit_price_cents` times a waste factor of 1.10, rounded half-up per line; and the total is the rounded labor plus the sum of the individually rounded lines. (Summing raw line values and rounding once at the end is a different formula and yields different cents; the per-line order is the pinned one.) `cost_variance_cents` is then set to `actual_cost_cents` minus `estimated_cost_cents`. The crew returns to `AVAILABLE` and its `completed_job_count` increases by 1, the break's `total_repair_cost_cents` grows by the actual cost, and the cascade runs in order: the break moves `IN_REPAIR` → `REPAIRED` with `repaired_at` stamped at the clock now; the break's `EXECUTED` isolation is restored (valves reopen, `customers_out_of_service` returns to 0); the advisory sampling window opens (§3.5); and a restoration job is auto-created in `PENDING` status against the completed work order (§3.6).

A `Dispatcher` may cancel a work order from `DRAFT` or from `DISPATCHED`. Cancelling a dispatched order releases its crew back to `AVAILABLE` and clears the dispatch window; cancelling a draft has no crew to release. `REPAIR_COMPLETE` and `CANCELLED` are terminal.

Crews themselves are registered by a `Dispatcher` with a unique `crew_name`, a `crew_size` greater than zero, an `equipment_class` of `LIGHT` or `HEAVY`, and an `hourly_rate_cents` greater than zero. A duplicate `crew_name` is rejected with `ERR_VALIDATION` (HTTP 400). A new crew starts `AVAILABLE` with `completed_job_count` 0.

### 3.5. Boil-Water Advisories and Water-Quality Sampling

Advisories arrive by two paths. The automatic path fires on isolation execution when the outage extent reaches 500 customers, as described in §3.3. The manual path lets a `WaterQualityOfficer` issue an advisory for a break by naming its `break_report_id`; the break must be in `CONFIRMED`, `ISOLATED`, `IN_REPAIR`, or `REPAIRED` status (otherwise `ERR_INVALID_STATE`), and if any advisory for the break is already `ISSUED` the manual issue is rejected with `ERR_ADVISORY_ALREADY_OPEN`. A manually issued advisory has `issue_reason` `MANUAL` and its `issued_by_user_id` recorded from the issuing officer's `X-User-ID`. Every advisory is born `ISSUED` with `issued_at` stamped at the clock now, `consecutive_pass_count` 0, `last_sample_at` null, and `lifted_at` / `lifted_by_user_id` null. The advisories of a break are listable under the break's nested route.

Rescission is evidence-based. A `WaterQualityOfficer` records water-quality tests against an `ISSUED` advisory by supplying the `advisory_id`, a `sampled_at` instant, a `chlorine_residual_mg_l` reading, and a `coliform_result` of `PASS` or `FAIL`. Each test's `test_outcome` is computed at recording: `PASS` when the coliform result is `PASS` and the chlorine residual is at least 0.20 milligrams per liter — a reading of exactly 0.20 passes — and `FAIL` otherwise. Recording a test mutates its advisory: a `PASS` outcome increments `consecutive_pass_count` by 1, while any `FAIL` resets it to 0, and `last_sample_at` is updated to the test's `sampled_at`. Two temporal rules guard sampling: `sampled_at` must not be earlier than the advisory's `issued_at` (otherwise `ERR_VALIDATION`), and when a previous sample exists, the new `sampled_at` must be at least 20 hours after `last_sample_at` — sampling sooner is rejected with `ERR_TEST_SAMPLE_TOO_SOON`. Both rules are evaluated after the ISSUED-state guard, the `issued_at` comparison before the spacing rule. The tests recorded against an advisory are listable under the advisory's nested route.

Lifting an advisory requires both evidence and independence. A `WaterQualityOfficer` lifts an `ISSUED` advisory only when its `consecutive_pass_count` is at least 2 at the moment of lifting (otherwise `ERR_ADVISORY_TESTS_INSUFFICIENT`) and the lifting officer's `X-User-ID` differs from the advisory's `issued_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`) — the issuer may never lift their own advisory, which is why auto-issued advisories, issued by the literal "system", can be lifted by any officer. A successful lift moves the advisory to `LIFTED` (terminal), stamps `lifted_at`, and records `lifted_by_user_id`.

### 3.6. Traffic Permits and Street Restoration

Street work needs a permit. A `Dispatcher` applies for a traffic permit by naming the `break_report_id`, the `street_block` identifier (such as OAK-100-BLK), a `valid_from` and `valid_to` validity window, and a `control_plan` of `LANE_CLOSURE`, `FULL_CLOSURE`, or `FLAGGING`. The named break must exist, but its status is not constrained. The validity window is half-open — it covers instants at or after `valid_from` and strictly before `valid_to` — and `valid_from` must be before `valid_to` (otherwise `ERR_VALIDATION`). Overlap is judged per street block: if any existing permit for the same `street_block` in `APPLIED` or `APPROVED` status has a validity window overlapping the new one under half-open semantics, the application is rejected with `ERR_PERMIT_OVERLAP`. Adjacency is not overlap — a new window starting exactly when an existing one ends is allowed. A new permit's `permit_status` is born `APPLIED`; a `PublicWorksEngineer` approves it, moving it to `APPROVED`. The permits of a break are listable under the break's nested route.

When a repair completes, a restoration job is auto-created against the finished work order with `restoration_status` `PENDING`, linked by its `work_order_id`, with `scheduled_start`, `scheduled_end`, `traffic_permit_id`, `patch_cost_cents`, and `completed_at` all null. Restoration jobs are listable globally, filterable by `work_order_id` and/or `traffic_permit_id`, with both supplied filters applying together.

Scheduling pins the patch window. A `Dispatcher` schedules a `PENDING` or `OVERDUE` job by supplying `scheduled_start`, `scheduled_end`, and a `traffic_permit_id`. Four conditions hold: the referenced permit must belong to the same break as the job's work order (otherwise `ERR_CROSS_REFERENCE_MISMATCH`); the permit must be `APPROVED` (otherwise `ERR_PERMIT_NOT_APPROVED`); the permit's half-open validity window must fully cover the scheduled window, meaning `valid_from` is at or before `scheduled_start` and `valid_to` is at or after `scheduled_end` (otherwise `ERR_PERMIT_WINDOW_MISMATCH`); and `scheduled_start` must be before `scheduled_end` (otherwise `ERR_VALIDATION`). Scheduling moves the job to `SCHEDULED` and records the window and permit.

Completion settles the street. A `Dispatcher` completes a `SCHEDULED` or `OVERDUE` job by recording the `patch_cost_cents` actually spent, which must be an integer (otherwise `ERR_VALIDATION`) of at least zero (otherwise `ERR_INVALID_AMOUNT`, HTTP 400). Completion stamps `completed_at`, moves the job to `COMPLETED`, and adds `patch_cost_cents` into the break's `total_restoration_cost_cents`. When every restoration job of a break is `COMPLETED`, the break itself moves from `REPAIRED` to `RESTORED`.

Restoration runs against a hard deadline. The operations checkpoint (§3.8) flags any job still `PENDING` or `SCHEDULED` whose parent break's `repaired_at` is more than 14 days in the past as `OVERDUE`; an overdue job can still be scheduled or completed normally.

### 3.7. Damage Claims and the Break Fiscal Ledger

Property-damage claims are filed by a `Dispatcher` against a break, naming the `break_report_id`, the `claimant_name`, and a `claimed_amount_cents` that must be greater than zero (otherwise `ERR_INVALID_AMOUNT`). Two timing gates apply: the break must be `CONFIRMED` or later (a `REPORTED` or `FALSE_ALARM` break cannot take claims), and filing must occur no more than 90 days after the break's `confirmed_at` — the boundary is inclusive, so filing exactly 90 days after confirmation is accepted, and any later filing is rejected with `ERR_CLAIM_FILED_LATE`. A new claim's `claim_status` is born `SUBMITTED` with `approved_amount_cents` null. The claims of a break are listable under the break's nested route.

Decisions belong to the `ClaimsAdjuster`. Approving a `SUBMITTED` claim sets `approved_amount_cents`, which must be greater than zero (otherwise `ERR_INVALID_AMOUNT`) and must not exceed `claimed_amount_cents` (otherwise `ERR_AMOUNT_EXCEEDS_CLAIMED`, HTTP 409); approval moves the claim to `APPROVED` and adds the approved amount into the break's `claims_liability_cents`. Denying moves a `SUBMITTED` claim to `DENIED` (terminal) with no fiscal effect.

Settlement moves money out of liability. Paying an `APPROVED` claim moves it to `PAID` (terminal), subtracts `approved_amount_cents` from the break's `claims_liability_cents`, and adds the same amount to the break's `total_claims_paid_cents`. Voiding an `APPROVED` claim is the compensating action: the claim moves to `VOIDED` (terminal) and the approved amount is subtracted from `claims_liability_cents` with no entry into paid totals. An approve followed by a void therefore leaves `claims_liability_cents`, `total_claims_paid_cents`, and `total_cost_cents` exactly as they were before the approval.

The break's fiscal ledger aggregates across all three cost streams. `total_repair_cost_cents` is the sum of `actual_cost_cents` over the break's `REPAIR_COMPLETE` work orders. `total_restoration_cost_cents` is the sum of `patch_cost_cents` over the break's `COMPLETED` restoration jobs. `claims_liability_cents` is the sum of `approved_amount_cents` over claims currently in `APPROVED` status — it excludes `PAID` and `VOIDED` claims. `total_claims_paid_cents` is the sum of `approved_amount_cents` over claims in `PAID` status. `total_cost_cents` is the sum of `total_repair_cost_cents`, `total_restoration_cost_cents`, and `total_claims_paid_cents` — note that open liability is deliberately excluded from the headline cost figure.

Closing a break is the engineer's final act and is guarded accordingly. A `PublicWorksEngineer` closes a `RESTORED` break only when no advisory for the break remains `ISSUED` (otherwise `ERR_ADVISORY_STILL_ACTIVE`) and no claim for the break remains `SUBMITTED` or `APPROVED` (otherwise `ERR_CLAIMS_OPEN`). `CLOSED` is terminal.

### 3.8. Operations Checkpoint and Repeat-Break Replacement Posture

A `System`-role operations checkpoint runs three sweeps against the logical clock and returns the ids it touched: `expired_permit_ids`, `overdue_restoration_ids`, and `updated_segment_ids`. `updated_segment_ids` lists only segments whose counts or condition posture actually changed during the sweep.

First, every traffic permit in `APPLIED` or `APPROVED` status whose `valid_to` is at or before the clock now moves to `EXPIRED` (terminal). Second, every restoration job in `PENDING` or `SCHEDULED` whose parent break's `repaired_at` plus 14 days is strictly before the clock now moves to `OVERDUE`. Third, every segment not in `REPLACED` status has its repeat-break counts and condition posture recomputed.

The repeat-break counts use a 36-month trailing window: breaks whose `confirmed_at` falls within the window from 36 calendar months before the clock now (the day clamped to the target month's length) through the clock now, inclusive of both boundaries. The official count, `repeat_break_count_36mo`, counts this segment's breaks currently in `REPAIRED`, `RESTORED`, or `CLOSED` status. The provisional count, `provisional_break_count_36mo`, counts this segment's breaks in `CONFIRMED`, `ISOLATED`, `IN_REPAIR`, `REPAIRED`, `RESTORED`, or `CLOSED` — it adds in-progress breaks, so it is at least the official count whenever a confirmed-but-unfinished break exists. Breaks still `REPORTED` and breaks marked `FALSE_ALARM` are excluded from both variants.

The condition posture derives from the official count: an official count of 3 or more puts the segment at `CANDIDATE`; exactly 2 puts it at `WATCH`; and 1 or fewer puts it at `NONE`. Because the derivation is re-run at every checkpoint, regression is cyclic — a `CANDIDATE` segment whose older breaks age out of the 36-month window falls back to `WATCH` when the count drops to exactly 2, and `WATCH` or `CANDIDATE` segments fall back to `NONE` when the count drops to 1 or fewer. Segments in `PROGRAMMED` or `REPLACED` are exempt from this auto-derivation and move only through the manual transitions below.

Replacement is the engineer's call. A `PublicWorksEngineer` programs a `CANDIDATE` segment, moving `condition_status` from `CANDIDATE` to `PROGRAMMED`, and later marks a `PROGRAMMED` segment replaced, moving it to the terminal `REPLACED`. Marking replaced stamps `replaced_at` with the clock now and freezes both repeat-break counts at their last computed values; from that moment, any attempt to confirm a new break against the segment is rejected with `ERR_SEGMENT_REPLACED`.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource; actions that transition an existing resource return HTTP 200 with the updated resource; reads return HTTP 200. Request and response field details are specified in the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /pipe-segments | Register a pipe segment | PublicWorksEngineer |
| GET | /pipe-segments/{id} | Get a pipe segment (condition posture + repeat-break counts) | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /pipe-segments/{id}/valves | List valves serving a segment | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /pipe-segments/{id}/pressure-anomalies | List pressure/flow anomalies observed on a segment | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /pipe-segments/{id}/break-reports | List break reports confirmed against a segment | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| POST | /pipe-segments/{id}/program-replacement | Program a CANDIDATE segment for replacement | PublicWorksEngineer |
| POST | /pipe-segments/{id}/mark-replaced | Mark a PROGRAMMED segment replaced (terminal); freezes counts | PublicWorksEngineer |
| POST | /valves | Register a valve on a segment | PublicWorksEngineer |
| POST | /pressure-anomalies | Post a SCADA pressure/flow anomaly observation | System |
| POST | /break-reports | File a break report (intake) | Dispatcher |
| GET | /break-reports/{id} | Get a break report including computed cost rollup fields | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| POST | /break-reports/{id}/confirm | Triage-confirm a report against a pipe segment | Dispatcher |
| POST | /break-reports/{id}/false-alarm | Mark a report as false alarm (terminal) | Dispatcher |
| POST | /break-reports/{id}/correlate | Correlate a pressure/flow anomaly with this break | Dispatcher |
| POST | /break-reports/{id}/close | Close a fully restored break (terminal) | PublicWorksEngineer |
| GET | /break-reports/{id}/isolation-events | List isolation plans for a break | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /break-reports/{id}/pressure-anomalies | List anomalies correlated to a break | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /break-reports/{id}/work-orders | List work orders for a break | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /break-reports/{id}/advisories | List boil-water advisories for a break | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /break-reports/{id}/traffic-permits | List traffic permits for a break | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /break-reports/{id}/damage-claims | List damage claims for a break | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| POST | /isolation-events | Plan a valve isolation for a CONFIRMED break; supersedes any prior PLANNED plan; OCC-guarded on the break | Dispatcher |
| POST | /isolation-events/{id}/execute | Execute a PLANNED isolation: close valves, compute outage extent, cascade | Dispatcher |
| POST | /crews | Register a repair crew | Dispatcher |
| GET | /crews/{id} | Get a crew (status, completed_job_count) | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| POST | /work-orders | Create a repair work order for a break (material sizing computed) | Dispatcher |
| GET | /work-orders/{id} | Get a work order | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /work-orders | List work orders, filterable by break or crew | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| POST | /work-orders/{id}/dispatch | Dispatch a crew (explicit crew_id or deterministic selector); computes estimated cost | Dispatcher |
| POST | /work-orders/{id}/arrive | Crew lead marks arrival on site | CrewLead |
| POST | /work-orders/{id}/complete | Crew lead logs actuals and completes the repair; cascades isolation restore + restoration creation | CrewLead |
| POST | /work-orders/{id}/cancel | Cancel a DRAFT or DISPATCHED work order (releases crew) | Dispatcher |
| POST | /boil-water-advisories | Manually issue a boil-water advisory for a break | WaterQualityOfficer |
| GET | /boil-water-advisories/{id} | Get an advisory (pass count, sampling state) | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| POST | /boil-water-advisories/{id}/lift | Rescind an advisory after two consecutive passing tests; segregation of duties enforced | WaterQualityOfficer |
| POST | /water-quality-tests | Record a water quality sample against an ISSUED advisory | WaterQualityOfficer |
| GET | /boil-water-advisories/{id}/tests | List water quality tests for an advisory | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /restoration-jobs/{id} | Get a restoration job | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| GET | /restoration-jobs | List restoration jobs, filterable by work order or permit | Dispatcher, CrewLead, WaterQualityOfficer, ClaimsAdjuster, PublicWorksEngineer, System |
| POST | /restoration-jobs/{id}/schedule | Schedule a pavement patch window under an approved permit | Dispatcher |
| POST | /restoration-jobs/{id}/complete | Complete a patch; rolls cost into the break and may restore the break | Dispatcher |
| POST | /traffic-permits | Apply for a traffic control permit on a street block | Dispatcher |
| POST | /traffic-permits/{id}/approve | Approve a permit | PublicWorksEngineer |
| POST | /damage-claims | File a property-damage claim against a break | Dispatcher |
| POST | /damage-claims/{id}/approve | Approve a claim for an amount | ClaimsAdjuster |
| POST | /damage-claims/{id}/deny | Deny a claim | ClaimsAdjuster |
| POST | /damage-claims/{id}/pay | Pay an approved claim | ClaimsAdjuster |
| POST | /damage-claims/{id}/void | Void an approved claim (compensating action) | ClaimsAdjuster |
| POST | /_clock/set_current_utc | Set the logical clock (startup default 2026-08-01T00:00:00Z; never falls back to wall clock) | System |
| POST | /ops-runs | Operations checkpoint: expire permits past valid_to, flag overdue restorations, recompute segment repeat-break posture | System |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ADVISORY_TESTS_INSUFFICIENT | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_TEST_SAMPLE_TOO_SOON | 409 |
| ERR_CROSS_REFERENCE_MISMATCH | 409 |
| ERR_SEGMENT_REPLACED | 409 |
| ERR_CLAIM_FILED_LATE | 409 |
| ERR_PERMIT_WINDOW_MISMATCH | 409 |
| ERR_PERMIT_OVERLAP | 409 |
| ERR_CREW_DOUBLE_BOOKED | 409 |
| ERR_CORRELATION_WINDOW | 409 |
| ERR_BREAK_NOT_ISOLATED | 409 |
| ERR_PERMIT_NOT_APPROVED | 409 |
| ERR_NO_CREW_AVAILABLE | 409 |
| ERR_DUPLICATE_ACTIVE_WORK_ORDER | 409 |
| ERR_ADVISORY_ALREADY_OPEN | 409 |
| ERR_ADVISORY_STILL_ACTIVE | 409 |
| ERR_CLAIMS_OPEN | 409 |
| ERR_INVALID_AMOUNT | 400 |
| ERR_AMOUNT_EXCEEDS_CLAIMED | 409 |
| ERR_INTERNAL | 500 |
