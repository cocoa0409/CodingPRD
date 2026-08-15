# Airport Snow Airfield Operations API — Product Requirements Document

## 1. Introduction

Winter storm events at a commercial airport are among the most operationally demanding scenarios an airfield operations department faces. When a snow event is forecast, the airport must activate a coordinated response: equipment must be staged and verified, runways and taxiways must be inspected and reported on, chemical de-icers must be dispensed under strict environmental caps, NOTAMs must be issued to alert air carriers, and — in the worst cases — a full airfield closure must be coordinated with airline station managers. Throughout the event, leadership needs live visibility into both the projected cost of the response and the actual accrued cost once work is complete.

This document specifies an API for managing the full lifecycle of an airport snow event, from initial forecast through activation, in-flight operations, and stand-down. The system models the airfield as a set of registered **surfaces** (runways, taxiways, aprons), tracks **condition reports** and **friction assessments** filed by inspectors against those surfaces, governs the issuance and rescission of **NOTAMs**, and enforces environmental and fiscal limits on chemical application. Operator shifts and equipment readiness feed a dual-variant cost model that distinguishes *provisional* (planned) cost from *final* (worked) cost.

A central design goal is **segregation of duties** combined with **posture-driven gating**: certain actions are only available when the SnowEvent is in an appropriate operational status, when every runway has reached a required surface state, or when a different operator than the one who authorized a chemical application is the one dispensing it. The API is intended for use by airport operations duty officers, airfield safety inspectors, snow fleet and chemical leads, airline coordination liaisons, and platform administrators.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a malformed header, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

Five roles are defined:

- `OpsController` — the airport operations duty officer. Creates snow events, drives the event lifecycle (ACTIVATE, ESCALATE, DE_ESCALATE, STAND_DOWN, CLOSE), drives the closure dimension (PROPOSE, RATIFY), takes surface status actions (RESTRICT, CLOSE, REOPEN, CLEAR), drafts and manages NOTAMs (ISSUE, REISSUE, RESCIND), schedules and completes operator shifts, and reads the per-event cost summary.
- `AirfieldInspector` — the airfield safety inspector. Files condition reports and friction assessments against surfaces.
- `MaintenanceLead` — the snow fleet and chemicals lead. Proposes, authorizes, dispenses, and voids chemical applications; manages equipment readiness (TAKE_OUT_OF_SERVICE, RETURN_TO_SERVICE).
- `AirlineCoordinator` — the airline station coordination liaison. Acknowledges proposed airfield closures and reads events and NOTAMs.
- `SystemAdmin` — the platform administrator. Registers airfield surfaces, chemical products, and equipment units; drives the logical clock.

A caller whose role is not permitted for the requested endpoint — or, on an action endpoint, whose role is not permitted for the specific action named in the request — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). For closure actions specifically, `ACKNOWLEDGE` requires `AirlineCoordinator` while `PROPOSE` and `RATIFY` require `OpsController`; the role check must consider the action value, not merely the endpoint.

All five roles are **opaque** identities: `X-User-ID` is an operator identifier not tied to any persisted entity row. The server may record it (for example, as `authorized_by` on a `ChemicalApplication` when a `MaintenanceLead` authorizes) but never compares it against any entity's `id`. For every role above, ownership-style checks against persisted entities are not performed; authorization is purely role-based, plus the explicit segregation-of-duties comparison between the caller's `X-User-ID` and a stored `authorized_by` on dispense.

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

All list endpoints accept two query parameters: `limit` and `offset`. The default `limit` is `10`, the minimum accepted value is `1`, the maximum accepted value is `100`, and the default `offset` is `0`. List responses populate `meta.limit`, `meta.offset`, `meta.total_count`, and `meta.has_more`. Unless an endpoint specifies otherwise, list results are sorted by `created_at` ascending.

### 2.4. Common Resource Properties

Every persisted resource carries `id` and `created_at`. The `id` is a server-minted UUID with no type prefix — it does not embed the entity name or any namespace. The `created_at` timestamp is an ISO 8601 UTC timestamp with three fractional digits, set at creation. Every resource in this domain also carries `updated_at` (ISO 8601 UTC with three fractional digits, refreshed on every mutation) and `version` (an integer that starts at `1` on creation and increments by exactly `1` on every state transition or mutation that the scaffold describes as a version-bumping side effect). There are no entities in this domain that omit `updated_at` or `version`. Client-supplied timestamp fields (`observed_at`, `measured_at`, `effective_from`, `effective_until`, `start_utc`, `end_utc`) are validated as ISO 8601 instants, then stored and returned verbatim as the client supplied them — the server does not reformat or normalize them.

### 2.5. Logical Clock

The server maintains a logical clock used for temporal validation. The startup default is exactly `2026-08-01T00:00:00Z`; the logical clock never falls back to wall-clock time. An administrative test-driving capability sets the logical clock to a supplied `to_iso8601` instant; the set is unconditional — the supplied instant may be earlier than, equal to, or later than the current clock value, with no monotonicity constraint. It responds with HTTP `200` and a `data` object carrying `current_utc`, the new logical clock time serialized as an ISO 8601 UTC timestamp with three fractional digits. Observation-time checks on `observed_at` (condition reports) and `measured_at` (friction assessments) compare against this logical clock: values strictly greater than the current logical clock are rejected.

### 2.6. Optimistic Concurrency Control

Two write endpoints in this domain accept an optimistic-concurrency token: filing a `ConditionReport` and recording a `FrictionAssessment`. The token field `expected_surface_version` is optional on both requests; when it is supplied it holds the `version` of the target `AirfieldSurface` as the client last observed it. The token is examined only at the optimistic-concurrency step (§2.9 step 6), after state preconditions have passed: a supplied non-integer value is rejected with `ERR_VALIDATION`, and a supplied integer that differs from the surface's current `version` — for example because another writer filed a report or took a surface action — is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a surface state it has not observed. When the field is omitted entirely, no concurrency check is performed and the write proceeds. No other endpoint in the domain takes a version field; requests to other endpoints must not include `expected_surface_version` or any analogous version-carrying input.

### 2.7. Existence Checks and Path Hierarchy

Where an endpoint path contains a resource identifier (for example a surface id inside a surface-action URL), the path id is resolved first. Where a request body references foreign keys, body references are then resolved **left to right** in the order the fields appear in the input contract — `event_id` before `surface_id` before `product_id` before `equipment_unit_id`. Each missing reference yields the resource-specific 404 variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`.

### 2.8. Precision and Rounding

Two rounding disciplines are used in this domain, and they are not interchangeable. **Chemical quantities** (`raw_quantity_lbs`, `authorized_quantity_lbs`, `seasonal_reserved_lbs`, `seasonal_dispensed_lbs`, `seasonal_available_lbs`, `chemical_used_lbs`, `event_remaining_lbs`, `product_available_lbs`) are carried at one decimal place, with **round half up** applied at the point specified in each calculation. **Money** (`line_cost_cents`, `estimated_cost_cents`, `actual_cost_cents`, `budget_cents`, `unit_cost_cents_per_lb`, `base_rate_cents_per_hour`, `hourly_rate_cents`) is integer cents, and every per-line cost is rounded half up to the cent **before** any summation; sum-then-round is not acceptable. The friction coefficient `mu_value` is validated only for the inclusive range `0.00` to `1.00`: the server neither rounds it nor enforces a number of decimal places on input, stores the value exactly as supplied, and compares it exactly against the thresholds defined for braking action.

### 2.9. Validation Priority

When a request is rejected, the first applicable rule in the following priority order determines the error. The order is not stylistic — a caller hitting two violations must see the earlier one.

1. Authentication: `X-User-ID` and `X-User-Role` present and well-formed (else `ERR_UNAUTHENTICATED`).
2. Role authorization: the caller's role is permitted for the endpoint and, on action endpoints, for the named action (else `ERR_UNAUTHORIZED_ROLE`).
3. Request well-formedness: required fields present, enum membership valid, numeric ranges satisfied (`mu_value` between `0.00` and `1.00` inclusive; `coverage_pct` between `0` and `100` inclusive; `depth_inches` at least `0`; `worked_hours` greater than `0`; lengths greater than `0`; `effective_from` strictly before `effective_until`; `start_utc` strictly before `end_utc`; `observed_at` and `measured_at` not ahead of the logical clock) (else `ERR_VALIDATION`).
4. Existence: path ids first, then body foreign keys left to right (else the per-resource `ERR_*_NOT_FOUND`).
5. State preconditions: the named action is valid for the current state of the target entity, and any cross-entity state gates are satisfied (else the per-entity state error — `ERR_INVALID_EVENT_STATE`, `ERR_EVENT_NOT_ACTIVE`, `ERR_INVALID_SURFACE_STATE`, `ERR_INVALID_NOTAM_STATE`, `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_SHIFT_STATE`).
6. Optimistic concurrency: `expected_surface_version` equals the surface's current `version` (else `ERR_STALE_VERSION`).
7. Product posture for chemical authorization: the referenced `ChemicalProduct` is `ACTIVE` (else `ERR_PRODUCT_CONSTRAINED`).
8. Environmental pools for chemical authorization: at least one pound of capacity remains in *both* the per-event pool and the product's seasonal pool (else `ERR_ENV_LIMIT_EXCEEDED`).
9. Surface-condition NOTAM safety: when issuing or reissuing a `SURFACE_CONDITION` NOTAM, the latest `REPORTED` friction assessment on the surface, if one exists, does not have `braking_action` of `POOR` or `NIL` (else `ERR_UNSAFE_NOTAM_CONDITION`).
10. Reopen friction floor: a surface reopen requires a latest `REPORTED` friction assessment whose `braking_action` is `GOOD` or `MEDIUM` (else `ERR_REOPEN_FRICTION_TOO_LOW`).

In rules 9 and 10, "latest" means the most recently created `REPORTED` assessment on the surface (greatest `created_at`), not the greatest `measured_at`.
11. Segregation of duties on dispense: the caller's `X-User-ID` differs from the application's recorded `authorized_by` (else `ERR_SEGREGATION_OF_DUTIES`).
12. Operator-shift overlap: a new shift's half-open window overlaps no other non-cancelled shift for the same `operator_code` (else `ERR_SHIFT_OVERLAP`).
13. NOTAM window overlap: a closed NOTAM window shares no instant — touching endpoints count as overlap — with any `ISSUED` NOTAM on the same surface and same `notam_type` (else `ERR_NOTAM_WINDOW_OVERLAP`).
14. Activation readiness floor: at least three `EquipmentUnit` rows are `READY` (else `ERR_EQUIPMENT_READINESS_SHORTFALL`).
15. Stand-down clearance: every `AirfieldSurface` is `OPEN` (else `ERR_SURFACE_NOT_CLEARED`).
16. Close cleanliness: no NOTAM on the event is `ISSUED` (else `ERR_ACTIVE_NOTAMS_REMAIN`).
17. Ratify runway posture: every `RUNWAY` surface is `CLOSED` (else `ERR_RUNWAYS_NOT_CLOSED`).
18. Ratify airline acknowledgement: `airline_acknowledged` is `true`, checked only after the runway-closure rule passes (else `ERR_AIRLINE_ACK_REQUIRED`).
19. Fiscal cap on chemical authorization: the projected event cost after this authorization does not exceed `budget_cents` (else `ERR_BUDGET_EXCEEDED`).
20. Equipment readiness on shift scheduling: when a new shift names an `equipment_unit_id`, that unit is `READY` (else `ERR_EQUIPMENT_NOT_READY`).

## 3. Business Logic & Workflows

### 3.1. Snow Event Lifecycle

An `OpsController` opens a storm response by creating a `SnowEvent` with an `event_code` (unique across all events, e.g. `SNOW-2026-01`; a duplicate `event_code` is rejected with `ERR_VALIDATION`), a `season_label` such as `2025-2026`, a `chemical_limit_lbs` per-event environmental cap on total chemical dispensed (strictly greater than zero), and a `budget_cents` fiscal cap on projected event cost (an integer, zero or greater). The new event starts with `status` = `FORECAST`, `closure_status` = `NONE`, `airline_acknowledged` = `false`, `activated_at` unset, and all three computed counters — `estimated_cost_cents`, `actual_cost_cents`, `chemical_used_lbs` — at zero.

Activation moves the event `FORECAST → ACTIVATED` and requires a fleet readiness floor: at least three `EquipmentUnit` rows in `READY` readiness must exist, otherwise the activation is rejected with `ERR_EQUIPMENT_READINESS_SHORTFALL`. On success, `activated_at` is stamped with the current logical clock time, serialized as an ISO 8601 UTC timestamp with three fractional digits, and the event's `version` increments. From `ACTIVATED` an `OpsController` may escalate the posture (`ACTIVATED → ESCALATED`) and later de-escalate (`ESCALATED → ACTIVATED`); each of these transitions also increments `version`. The event's `status` is the operational gate for most downstream activity: filing condition reports, recording friction assessments, taking surface actions, authorizing chemical applications, and scheduling shifts all require the referenced event to be in `ACTIVATED` or `ESCALATED`, and reject with `ERR_EVENT_NOT_ACTIVE` otherwise. Proposing a chemical application (§3.8) and drafting a NOTAM (§3.6) are not gated on event status.

All event-lifecycle transitions are driven through a single event-actions capability whose request body carries an `action` field naming the verb — `ACTIVATE`, `ESCALATE`, `DE_ESCALATE`, `STAND_DOWN`, or `CLOSE`.

Stand-down is initiated from `ACTIVATED` or `ESCALATED` and requires every `AirfieldSurface` in the system to be `OPEN`; any surface still `RESTRICTED` or `CLOSED` produces `ERR_SURFACE_NOT_CLEARED`. A successful stand-down moves the event into `STANDING_DOWN` and, as a side effect, reconciles the closure dimension: a `closure_status` of `RATIFIED` flips to `LIFTED`, while a `closure_status` of `PROPOSED` flips back to `NONE` with `airline_acknowledged` reset to `false`. The event's `version` increments.

Final closure moves `STANDING_DOWN → CLOSED` and requires that no NOTAM on this event has `status` = `ISSUED`; any outstanding issued NOTAM produces `ERR_ACTIVE_NOTAMS_REMAIN`. On close, `actual_cost_cents` is frozen as the final cost reconciliation, `estimated_cost_cents` is recomputed (and reaches zero once no shifts remain `SCHEDULED` and no applications remain `AUTHORIZED`), and `version` increments. `CLOSED` is terminal.

### 3.2. Closure Coordination with Airlines

The closure dimension runs in parallel with the operational status. From an event in `ACTIVATED` or `ESCALATED`, an `OpsController` may propose an airfield closure (`closure_status`: `NONE → PROPOSED`); proposing from any other operational state is rejected with `ERR_INVALID_EVENT_STATE`. The act of proposing sets `airline_acknowledged` to `false` and increments `version`.

An `AirlineCoordinator` then acknowledges the proposal. Acknowledgement is a self-loop on `PROPOSED` that sets `airline_acknowledged` to `true` and increments `version`; it does not change `closure_status`. Ratification by an `OpsController` moves `PROPOSED → RATIFIED` but is gated by two checks evaluated in order: first, every `AirfieldSurface` whose `surface_type` is `RUNWAY` must have `status` = `CLOSED`, otherwise `ERR_RUNWAYS_NOT_CLOSED`; second, only after the runway check passes, `airline_acknowledged` must be `true`, otherwise `ERR_AIRLINE_ACK_REQUIRED`. A successful ratify increments `version`. Lifting a ratified closure, or unwinding a proposed one, is not a direct action — both happen as side effects of stand-down as described in §3.1.

### 3.3. Airfield Surfaces and Status Actions

A `SystemAdmin` registers each `AirfieldSurface` with a unique `surface_code` (e.g. `RWY-09L`; a duplicate `surface_code` is rejected with `ERR_VALIDATION`), a `surface_type` of `RUNWAY`, `TAXIWAY`, or `APRON`, positive `length_ft` and `width_ft` in feet, and a `priority_rank` integer. The server computes `area_sqft` as `length_ft` multiplied by `width_ft`; any client-supplied value for `area_sqft` is ignored. New surfaces start with `status` = `OPEN`, `current_condition_code` unset, and `active_notam_count` = `0`.

An `OpsController` drives surface posture through surface actions. `RESTRICT` moves `OPEN → RESTRICTED`; `CLOSE` moves `OPEN → CLOSED` or `RESTRICTED → CLOSED`; `REOPEN` moves `CLOSED → RESTRICTED`; `CLEAR` moves `RESTRICTED → OPEN`. Every surface action names an `event_id` in its payload, and the referenced `SnowEvent` must be in `ACTIVATED` or `ESCALATED` — otherwise the action is rejected with `ERR_EVENT_NOT_ACTIVE`. Within the state-precondition tier of §2.9, the surface's own transition validity (`ERR_INVALID_SURFACE_STATE`) is evaluated before the event-active gate (`ERR_EVENT_NOT_ACTIVE`). Every successful surface action increments the surface's `version`.

`REOPEN` carries an additional safety gate: the latest `FrictionAssessment` on this surface with `status` = `REPORTED` — latest meaning most recently created, by `created_at` — must exist and have `braking_action` of `GOOD` or `MEDIUM`. If no such assessment exists, or the latest is `MEDIUM_POOR`, `POOR`, or `NIL`, the reopen is rejected with `ERR_REOPEN_FRICTION_TOO_LOW`.

Closing a surface fires a three-link cascade. **Cascade link 1:** every `ConditionReport` on this surface still in `FILED` status becomes `SUPERSEDED`. **Cascade link 2:** each such supersession flips every `ISSUED` `Notam` whose `source_report_id` names that report to `REISSUE_REQUIRED`. **Cascade link 3:** each NOTAM flip to `REISSUE_REQUIRED` causes this surface's `active_notam_count` to be recomputed — only `ISSUED` rows count.

### 3.4. Condition Reports and Field Condition Codes

An `AirfieldInspector` files a `ConditionReport` against a surface by supplying `event_id`, `surface_id`, a `contaminant_type` drawn from `DRY`, `WET`, `DRY_SNOW`, `WET_SNOW`, `COMPACTED_SNOW`, `ICE`, `SLUSH`, or `STANDING_WATER`, a `coverage_pct` that must be an integer between `0` and `100` inclusive, a non-negative numeric `depth_inches`, and an `observed_at` timestamp not ahead of the logical clock. The request may also carry `expected_surface_version` per §2.6; a supplied stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), and an omitted value skips the check.

On creation the server derives `condition_code` from the RCAM-like base table and a downgrade rule. The base code by contaminant is: `DRY` → `6`, `WET` → `5`, `DRY_SNOW` → `4`, `WET_SNOW` → `3`, `COMPACTED_SNOW` → `2`, `SLUSH` → `2`, `STANDING_WATER` → `2`, `ICE` → `1`. If `coverage_pct` is strictly greater than `50` **and** `depth_inches` is at least `0.25`, the base is reduced by `1`. The resulting code is floored at `0`, so `condition_code` is always an integer in `0..6`. The new report starts with `status` = `FILED` and `superseded_by_id` unset, and the surface's `current_condition_code` is updated to this newly derived code.

Filing a newer report for the same (`event_id`, `surface_id`) supersedes the prior `FILED` report: the older row's `status` becomes `SUPERSEDED`, its `superseded_by_id` is set to the newer report's `id`, every `ISSUED` `Notam` whose `source_report_id` names the superseded report flips to `REISSUE_REQUIRED`, and each such flip recomputes the surface's `active_notam_count`. Filing a report also increments the parent surface's `version` — which is exactly what the next filer's `expected_surface_version` must reflect.

### 3.5. Friction Assessments and Braking Action

An `AirfieldInspector` records a `FrictionAssessment` by supplying `event_id`, `surface_id`, a numeric `mu_value` in the inclusive range `0.00` to `1.00` (any precision is accepted; per §2.8 the server neither rounds it nor enforces decimal places), and a `measured_at` timestamp not ahead of the logical clock. As with condition reports, the request may carry `expected_surface_version` per §2.6; a supplied stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), and an omitted value skips the check.

On creation the server derives `braking_action` from `mu_value` against four inclusive lower-bound thresholds, evaluated from highest to lowest. If `mu_value` is at least `0.50`, `braking_action` is `GOOD`. Otherwise, if `mu_value` is at least `0.36`, it is `MEDIUM`. Otherwise, if `mu_value` is at least `0.26`, it is `MEDIUM_POOR`. Otherwise, if `mu_value` is at least `0.10`, it is `POOR`. Otherwise it is `NIL`. Because the lower bounds are inclusive, a `mu_value` of exactly `0.36` yields `MEDIUM`, not `MEDIUM_POOR`. The new assessment starts with `status` = `REPORTED` and `superseded_by_id` unset.

Recording a newer assessment for the same (`event_id`, `surface_id`) supersedes the prior `REPORTED` one: the older row's `status` becomes `SUPERSEDED`, its `superseded_by_id` is set to the newer assessment's `id`, every `ISSUED` `Notam` whose `source_assessment_id` names the superseded assessment flips to `REISSUE_REQUIRED`, and each flip recomputes the surface's `active_notam_count`. Recording an assessment also increments the parent surface's `version`.

### 3.6. NOTAM Lifecycle and Effective Windows

An `OpsController` drafts a `Notam` by supplying `event_id`, `surface_id`, a `notam_type` of `SURFACE_CONDITION`, `RUNWAY_CLOSURE`, or `CHEMICAL_TREATMENT`, an effective window bounded by `effective_from` and `effective_until`, and a free-text `message`. The window is a **closed interval** — both endpoints are inclusive — and `effective_from` must be strictly earlier than `effective_until`. Optionally, the draft may link evidence via `source_assessment_id` (a `FrictionAssessment`) or `source_report_id` (a `ConditionReport`); when supplied, each link must reference an existing entity — resolved in that order, assessment first — yielding `ERR_ASSESSMENT_NOT_FOUND` or `ERR_REPORT_NOT_FOUND` otherwise. Drafting is not gated on the referenced event's status. A new NOTAM starts in `DRAFT`.

Issuance (`DRAFT → ISSUED`) is gated by three checks. First, the referenced surface must be `RESTRICTED` or `CLOSED`; issuing against an `OPEN` surface is rejected with `ERR_INVALID_SURFACE_STATE`. Second, when `notam_type` is `SURFACE_CONDITION`, the latest `REPORTED` `FrictionAssessment` on the surface — latest meaning most recently created, by `created_at` — if one exists, must have `braking_action` other than `POOR` or `NIL`; otherwise the issuance is rejected with `ERR_UNSAFE_NOTAM_CONDITION`. Third, the closed window `[effective_from, effective_until]` must share no instant with any other `ISSUED` NOTAM on the same surface with the same `notam_type` — and under closed-interval semantics, touching endpoints count as overlap. A conflict yields `ERR_NOTAM_WINDOW_OVERLAP`. A successful issue adds `1` to the surface's `active_notam_count` and increments the NOTAM's `version`. Like reissuance, issuance also honors `effective_from` and/or `effective_until` supplied in the action payload, overriding the drafted window.

An `ISSUED` NOTAM whose source report or source assessment is superseded flips automatically to `REISSUE_REQUIRED`; that flip subtracts `1` from the surface's `active_notam_count` because `REISSUE_REQUIRED` rows are not counted. Reissuance (`REISSUE_REQUIRED → ISSUED`) is performed by an `OpsController` and may supply a new `effective_from` and/or `effective_until`; if new values are not supplied, the existing window is reused. Reissue re-applies the same three gates as initial issuance — surface posture, surface-condition safety, and closed-interval overlap against other `ISSUED` NOTAMs of the same surface and type — and on success adds `1` back to `active_notam_count` and increments `version`. On the notam-actions endpoint generally, the NOTAM's state precondition (`ERR_INVALID_NOTAM_STATE`) is evaluated before the well-formedness of any supplied window overrides, so an action that mismatches the NOTAM's status is rejected with `ERR_INVALID_NOTAM_STATE` even if the payload also carries a malformed window.

Rescission is allowed from either `ISSUED` or `REISSUE_REQUIRED`, and in both cases requires the referenced surface to be `OPEN`; rescinding while the surface is `RESTRICTED` or `CLOSED` is rejected with `ERR_INVALID_SURFACE_STATE`. Rescinding from `ISSUED` subtracts `1` from `active_notam_count`; rescinding from `REISSUE_REQUIRED` does not change the count (the row was already not counted). Both paths move the NOTAM to `RESCINDED` and increment `version`. Attempting an action that does not match the NOTAM's current status — for example rescinding a `DRAFT` or issuing an already-`ISSUED` NOTAM — is rejected with `ERR_INVALID_NOTAM_STATE`.

### 3.7. Chemical Products and Seasonal Accounting

A `SystemAdmin` registers each `ChemicalProduct` with a unique `product_code` (e.g. `NAAC-01`; a duplicate `product_code` is rejected with `ERR_VALIDATION`), a positive `base_rate_lbs_per_1000sqft` baseline application rate, a non-negative integer `unit_cost_cents_per_lb`, and a positive `seasonal_limit_lbs` season-wide environmental cap. The server maintains three computed counters on each product: `seasonal_reserved_lbs` is the sum of `authorized_quantity_lbs` over this product's `AUTHORIZED` applications; `seasonal_dispensed_lbs` is the sum of `authorized_quantity_lbs` over this product's `DISPENSED` applications; and `seasonal_available_lbs` is `seasonal_limit_lbs` minus `seasonal_dispensed_lbs` minus `seasonal_reserved_lbs`. The three counters obey a conserved-quota invariant: at all times, `seasonal_dispensed_lbs` plus `seasonal_reserved_lbs` plus `seasonal_available_lbs` equals `seasonal_limit_lbs`. A new product starts with `status` = `ACTIVE`, `seasonal_reserved_lbs` = `0`, `seasonal_dispensed_lbs` = `0`, and `seasonal_available_lbs` = `seasonal_limit_lbs`.

A product's `status` flips from `ACTIVE` to `CONSTRAINED` automatically when a dispense pushes `seasonal_dispensed_lbs` to at least 90% of `seasonal_limit_lbs`. That flip has teeth: every `ChemicalApplication` on this product still in `PROPOSED` status becomes `REJECTED`.

### 3.8. Chemical Applications — Proposal, Authorization, Dispense, Void

A `MaintenanceLead` proposes a `ChemicalApplication` by supplying `event_id`, `surface_id`, `product_id`, and `pavement_temp_f` (the pavement temperature in Fahrenheit at proposal time). Proposal requires only that the referenced event, surface, and product exist; it is not gated on the event's `status` — the `ACTIVATED`/`ESCALATED` requirement applies at authorization, not proposal. The server computes `raw_quantity_lbs` as the physics-driven planned quantity. The surface's `area_sqft` is divided by `1000` to yield area units. A temperature factor is selected from `pavement_temp_f`: if the temperature is strictly below `15` degrees, the factor is `1.25`; if the temperature is between `15` and `28` degrees inclusive, the factor is `1.10`; otherwise (strictly above `28`) the factor is `1.00`. The raw quantity is the area units multiplied by the product's `base_rate_lbs_per_1000sqft` multiplied by the selected temperature factor, rounded half up to one decimal place. The new application starts with `status` = `PROPOSED`, `authorized_quantity_lbs` unset, `capped` = `false`, `authorized_by` unset, and `line_cost_cents` = `0`.

Authorization (`PROPOSED → AUTHORIZED`) by a `MaintenanceLead` is the most heavily gated action in the domain, and its checks are evaluated in the priority order listed in §2.9: the application's own state precondition (`ERR_INVALID_APPLICATION_STATE`) first, then the referenced event must be `ACTIVATED` or `ESCALATED` (else `ERR_EVENT_NOT_ACTIVE`); the referenced product must be `ACTIVE` (else `ERR_PRODUCT_CONSTRAINED`); at least one pound of capacity must remain in *both* environmental pools (else `ERR_ENV_LIMIT_EXCEEDED`); and the projected event cost after this authorization must not exceed `budget_cents` (else `ERR_BUDGET_EXCEEDED`). The projected event cost is computed as the event's current `estimated_cost_cents` — which does not yet include this still-`PROPOSED` application — plus this application's would-be `line_cost_cents`; authorization is rejected exactly when that sum is strictly greater than `budget_cents`.

The environmental pools are computed as follows. The per-event remaining capacity, `event_remaining_lbs`, is the event's `chemical_limit_lbs` minus its `chemical_used_lbs` minus the sum of `authorized_quantity_lbs` over this event's `AUTHORIZED` applications. The product's available pool, `product_available_lbs`, is its `seasonal_available_lbs`. Authorization requires the smaller of those two pools to be strictly greater than zero; the boundary at equality is inclusive, so if the raw quantity exactly equals the available capacity, authorization proceeds in full.

On successful authorization, `authorized_quantity_lbs` is set to the minimum of three values: `raw_quantity_lbs`, `event_remaining_lbs`, and `product_available_lbs`. The `capped` flag is set to `true` when `authorized_quantity_lbs` is strictly less than `raw_quantity_lbs`, and `false` when they are equal. The application's `line_cost_cents` is set to `authorized_quantity_lbs` multiplied by the product's `unit_cost_cents_per_lb`, rounded half up to the cent. The product's `seasonal_reserved_lbs` increases by `authorized_quantity_lbs` (and `seasonal_available_lbs` is recomputed), the application's `authorized_by` is stamped with the caller's `X-User-ID`, the event's `estimated_cost_cents` is recomputed because this application now contributes to the provisional variant, and the application's `version` increments.

Dispensing (`AUTHORIZED → DISPENSED`) enforces **segregation of duties**: the caller's `X-User-ID` must differ from the application's `authorized_by`, otherwise the dispense is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful dispense moves the product's `seasonal_reserved_lbs` down by `authorized_quantity_lbs` and its `seasonal_dispensed_lbs` up by the same amount, with `seasonal_available_lbs` recomputed; adds `authorized_quantity_lbs` to the event's `chemical_used_lbs`; recomputes both `actual_cost_cents` (this application enters the final variant) and `estimated_cost_cents` (it leaves the provisional variant); and then fires the three-link constrained cascade — the dispensed-total mutation is compared against 90% of `seasonal_limit_lbs`, crossing that threshold flips the product `ACTIVE → CONSTRAINED`, and that flip rejects every `PROPOSED` application on the product. The application's `version` increments.

Voiding (`AUTHORIZED → VOIDED`) compensates the authorization: the product's `seasonal_reserved_lbs` decreases by `authorized_quantity_lbs` (with `seasonal_available_lbs` recomputed), the event's `estimated_cost_cents` is recomputed because the application leaves the provisional input set, and `version` increments. `DISPENSED`, `REJECTED`, and `VOIDED` are terminal for an application; attempting an action that does not match the current status — for example dispensing a `PROPOSED` application or voiding a `DISPENSED` one — is rejected with `ERR_INVALID_APPLICATION_STATE`.

### 3.9. Equipment and Operator Shifts

A `SystemAdmin` registers each `EquipmentUnit` with a unique `unit_code` (e.g. `PLOW-01`; a duplicate `unit_code` is rejected with `ERR_VALIDATION`), a `unit_type` of `PLOW`, `BROOM`, `DEICER`, or `BLOWER`, and a non-negative integer `hourly_rate_cents`. New units start with `readiness` = `READY`. A `MaintenanceLead` may take a unit out of service (`READY → OUT_OF_SERVICE`) and return it (`OUT_OF_SERVICE → READY`); each transition increments the unit's `version`. A readiness action that does not match the unit's current readiness — for example `TAKE_OUT_OF_SERVICE` on an already `OUT_OF_SERVICE` unit — is rejected with `ERR_INVALID_EQUIPMENT_STATE` (HTTP 409).

An `OpsController` schedules an `OperatorShift` against an event by supplying `operator_code` (an operator identifier string), `event_id`, a non-negative `base_rate_cents_per_hour`, a half-open window `[start_utc, end_utc)` with `start_utc` strictly before `end_utc`, and optionally an `equipment_unit_id`. The overlap check is scoped per `operator_code`: the new half-open window must overlap no other non-`CANCELLED` shift for the same operator, with touching endpoints (one shift's `end_utc` equal to another's `start_utc`) allowed; a conflict yields `ERR_SHIFT_OVERLAP`. When `equipment_unit_id` is supplied, the referenced unit must be `READY`; scheduling against an `OUT_OF_SERVICE` unit is rejected with `ERR_EQUIPMENT_NOT_READY`. A new shift starts with `status` = `SCHEDULED`, `worked_hours` unset, and `line_cost_cents` = `0`, and its creation recomputes the event's `estimated_cost_cents` because the shift enters the provisional input set.

Completing a shift (`SCHEDULED → COMPLETED`) requires `worked_hours` (strictly greater than zero) in the action payload. On completion the shift's `line_cost_cents` is computed — as the rounded labor line plus, when an `equipment_unit_id` is set, the separately rounded equipment line (§3.10) — and the event's `actual_cost_cents` is recomputed because the shift enters the final input set; `version` increments. Cancelling a shift (`SCHEDULED → CANCELLED`) recomputes `estimated_cost_cents` because the shift leaves the provisional input set and increments `version`. Attempting an action that does not match the current status — for example completing an already-`COMPLETED` shift — is rejected with `ERR_INVALID_SHIFT_STATE`; on shift-actions the state precondition is evaluated before the well-formedness of `worked_hours`, so a `COMPLETE` against a non-`SCHEDULED` shift yields `ERR_INVALID_SHIFT_STATE` even when `worked_hours` is missing or malformed.

### 3.10. Event Cost Accrual — Provisional and Actual Variants

The event cost model is dual-variant and recomputed whenever any shift or chemical application of the event changes status (create, authorize, dispense, void, complete, cancel) and again at event close. The rounding order is pinned: each per-line cost is rounded half up to the cent **first**, and only then are the rounded lines summed. Sum-then-round is rejected.

A shift contributes two kinds of lines. Its **labor line** uses `h` hours — planned hours (`end_utc` minus `start_utc`) for a `SCHEDULED` shift, `worked_hours` for a `COMPLETED` shift — and is the sum of the regular-hours portion and the overtime portion. The regular-hours portion is the smaller of `h` and `8` hours, multiplied by `base_rate_cents_per_hour`. The overtime portion is the larger of zero and (`h` minus `8`), multiplied by `base_rate_cents_per_hour`, multiplied by `1.5`. The labor line is rounded half up to the cent. A shift's **equipment line** exists only when `equipment_unit_id` is set: it is `h` multiplied by the unit's `hourly_rate_cents`, rounded half up to the cent.

A chemical application contributes a **chemical line** equal to its `authorized_quantity_lbs` multiplied by the product's `unit_cost_cents_per_lb`, rounded half up to the cent.

The **provisional variant**, `estimated_cost_cents`, is the sum of lines over shifts with `status` = `SCHEDULED` plus applications with `status` = `AUTHORIZED`. The **final variant**, `actual_cost_cents`, is the sum of lines over shifts with `status` = `COMPLETED` plus applications with `status` = `DISPENSED`. `CANCELLED` shifts and `REJECTED` or `VOIDED` applications are excluded from both variants. Identical records yield a different total whenever planned hours differ from worked hours. An `OpsController` reads both variants plus `chemical_used_lbs` via the event's cost-summary capability, whose `data` object carries exactly three fields: `estimated_cost_cents`, `actual_cost_cents`, and `chemical_used_lbs`.

### 3.11. Dispatch Order

During an active event, an `OpsController` or `MaintenanceLead` may retrieve the priority surface sequencing for clearing operations. The path event id must resolve to an existing `SnowEvent` (else `ERR_EVENT_NOT_FOUND`), though the eligible set is not otherwise scoped to the event: it is every `AirfieldSurface` in the system with `status` of `RESTRICTED` or `CLOSED`. The ordering is by `priority_rank` ascending; ties break by `created_at` ascending. If no surface is eligible, the result is an empty array — this is not an error. The ordering is a deterministic total order; `id` is never used for ranking or tie-breaks. Each element of the array is the full serialized `AirfieldSurface` resource. The response is a non-paginated array: `limit` and `offset` are not accepted, and `meta` carries no pagination fields.

## 4. Endpoint Definitions

New resources are returned with HTTP `201`; modifications to existing resources (including all action endpoints) return HTTP `200`. Reads return HTTP `200`. All responses use the envelope defined in §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/snow-events` | Create a snow event shell (starts FORECAST) | `OpsController` |
| GET | `/snow-events` | List snow events (filters: `status?`, `season_label?`) | `OpsController`, `AirlineCoordinator`, `SystemAdmin` |
| GET | `/snow-events/{id}` | Read one snow event (costs, statuses, version) | `OpsController`, `AirlineCoordinator`, `SystemAdmin` |
| POST | `/snow-events/{id}/event-actions` | Lifecycle action: ACTIVATE / ESCALATE / DE_ESCALATE / STAND_DOWN / CLOSE | `OpsController` |
| POST | `/snow-events/{id}/closure-actions` | Closure action: PROPOSE / RATIFY (OpsController), ACKNOWLEDGE (AirlineCoordinator) | `OpsController`, `AirlineCoordinator` |
| GET | `/snow-events/{id}/dispatch-order` | Priority surface sequencing (RESTRICTED/CLOSED, priority_rank ASC, created_at ASC) | `OpsController`, `MaintenanceLead` |
| GET | `/snow-events/{id}/cost-summary` | Dual-variant cost read | `OpsController` |
| POST | `/airfield-surfaces` | Register an airfield surface | `SystemAdmin` |
| GET | `/airfield-surfaces` | List surfaces (filters: `status?`, `surface_type?`) | `OpsController`, `AirfieldInspector`, `MaintenanceLead`, `SystemAdmin` |
| GET | `/airfield-surfaces/{id}` | Read one surface | `OpsController`, `AirfieldInspector`, `MaintenanceLead`, `SystemAdmin` |
| POST | `/airfield-surfaces/{id}/surface-actions` | Surface action: RESTRICT / CLOSE / REOPEN / CLEAR | `OpsController` |
| POST | `/condition-reports` | File a condition report (supersedes prior FILED for same event/surface) | `AirfieldInspector` |
| GET | `/condition-reports` | List condition reports (filters: `event_id?`, `surface_id?`, `status?`) | `OpsController`, `AirfieldInspector` |
| GET | `/condition-reports/{id}` | Read one condition report | `OpsController`, `AirfieldInspector` |
| POST | `/friction-assessments` | Record a friction measurement (supersedes prior REPORTED for same event/surface) | `AirfieldInspector` |
| GET | `/friction-assessments` | List friction assessments (filters: `event_id?`, `surface_id?`, `status?`) | `OpsController`, `AirfieldInspector` |
| GET | `/friction-assessments/{id}` | Read one friction assessment | `OpsController`, `AirfieldInspector` |
| POST | `/notams` | Draft a NOTAM (starts DRAFT) | `OpsController` |
| POST | `/notams/{id}/notam-actions` | NOTAM action: ISSUE / REISSUE / RESCIND | `OpsController` |
| GET | `/notams` | List NOTAMs (filters: `event_id?`, `surface_id?`, `status?`, `notam_type?`, `source_assessment_id?`, `source_report_id?`) | `OpsController`, `AirlineCoordinator` |
| GET | `/notams/{id}` | Read one NOTAM | `OpsController`, `AirlineCoordinator` |
| POST | `/chemical-products` | Register a chemical product with its seasonal cap | `SystemAdmin` |
| GET | `/chemical-products` | List chemical products (filters: `product_code?`, `status?`) | `SystemAdmin`, `MaintenanceLead`, `OpsController` |
| GET | `/chemical-products/{id}` | Read one chemical product (counters, status) | `SystemAdmin`, `MaintenanceLead`, `OpsController` |
| POST | `/chemical-applications` | Propose a chemical application | `MaintenanceLead` |
| POST | `/chemical-applications/{id}/application-actions` | Application action: AUTHORIZE / DISPENSE / VOID | `MaintenanceLead` |
| GET | `/chemical-applications` | List chemical applications (filters: `event_id?`, `surface_id?`, `product_id?`, `status?`) | `MaintenanceLead`, `OpsController` |
| GET | `/chemical-applications/{id}` | Read one chemical application | `MaintenanceLead`, `OpsController` |
| POST | `/equipment-units` | Register snow-removal equipment (starts READY) | `SystemAdmin` |
| POST | `/equipment-units/{id}/readiness-actions` | Readiness action: TAKE_OUT_OF_SERVICE / RETURN_TO_SERVICE | `MaintenanceLead` |
| POST | `/operator-shifts` | Schedule an operator shift | `OpsController` |
| POST | `/operator-shifts/{id}/shift-actions` | Shift action: COMPLETE (with `worked_hours`) / CANCEL | `OpsController` |
| GET | `/operator-shifts` | List operator shifts (filters: `operator_code?`, `event_id?`, `equipment_unit_id?`, `status?`) | `OpsController` |
| GET | `/operator-shifts/{id}` | Read one operator shift | `OpsController` |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: advance the logical clock to `to_iso8601` | `SystemAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_SURFACE_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_NOTAM_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_EVENT_STATE` | 409 |
| `ERR_EVENT_NOT_ACTIVE` | 409 |
| `ERR_INVALID_SURFACE_STATE` | 409 |
| `ERR_INVALID_NOTAM_STATE` | 409 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_INVALID_SHIFT_STATE` | 409 |
| `ERR_PRODUCT_CONSTRAINED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_UNSAFE_NOTAM_CONDITION` | 409 |
| `ERR_REOPEN_FRICTION_TOO_LOW` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ENV_LIMIT_EXCEEDED` | 422 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_NOTAM_WINDOW_OVERLAP` | 409 |
| `ERR_EQUIPMENT_READINESS_SHORTFALL` | 409 |
| `ERR_SURFACE_NOT_CLEARED` | 409 |
| `ERR_ACTIVE_NOTAMS_REMAIN` | 409 |
| `ERR_RUNWAYS_NOT_CLOSED` | 409 |
| `ERR_AIRLINE_ACK_REQUIRED` | 409 |
| `ERR_EQUIPMENT_NOT_READY` | 409 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_INVALID_EQUIPMENT_STATE` | 409 |

Requests that match no defined route are rejected with `ERR_NOT_FOUND` (HTTP 404); requests using an unsupported method on a defined route are rejected with `ERR_METHOD_NOT_ALLOWED` (HTTP 405); an unexpected server failure yields `ERR_INTERNAL` (HTTP 500). These generic identifiers exist outside the domain catalogue above but use the same error envelope.
