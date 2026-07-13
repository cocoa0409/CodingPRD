# Medical Courier & Specimen Logistics API — Product Requirements Document

## 1. Introduction

The Medical Courier & Specimen Logistics platform coordinates the movement of laboratory specimens along scheduled and STAT (urgent) courier runs, where a single dropped connection or an unnoticed temperature excursion can invalidate a patient's diagnostic sample. This API is the operational backbone for that work: it models the pickup/dropoff manifest of a route, the chain-of-custody and temperature history of every specimen aboard it, the drivers and vehicles credentialed to carry that cargo, and the per-stop and per-mile billing owed by the ordering laboratory. Its central obligation is auditability — every scan, every excursion, every missed stop, and every dollar charged must be reconstructable after the fact.

The system serves four distinct operator communities that rarely overlap in their day-to-day surface: dispatch controllers who build and crew routes, couriers who physically execute them, laboratories that order recurring runs and watch their spending, and compliance staff who govern driver credentials and adjudicate exceptions. Because specimens carry two independent conditions at once — where they are in the custody chain and whether their integrity is still intact — the platform tracks these dimensions separately, so that a sample can be simultaneously delivered and compromised. The sections below define the global contract every client shares, the business workflows that move a run from a planned manifest to a settled invoice, and the complete endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. The entire API is mounted under `/med-courier` (the logical clock utility excepted).

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting an `X-User-Role` that is not one of the four recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation — or an ownership-scoped role reaches for a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are `Dispatcher`, `Driver`, `LabClient`, and `ComplianceOfficer`.

- When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Dispatchers are the operations controllers who build rate cards, laboratories, vehicles, and templates, crew and dispatch routes, complete runs, and generate, issue, and void billing.
- When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`; ownership checks compare a route's `driver_id` foreign key to `X-User-ID`. A driver may record scans only against stops belonging to a route whose `driver_id` equals their own `X-User-ID`, and may read only their own routes, stops, specimens, and scan events.
- When `X-User-Role` is `LabClient`, `X-User-ID` is the `id` of the acting `LabClient`; ownership checks compare a resource's `lab_client_id` foreign key to `X-User-ID`. A laboratory may build routes, stops, and specimens only under its own `lab_client_id`, and may read only its own routes, specimens, exceptions, and billings.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it in context but does not compare it to any entity's `id`. Compliance officers govern driver credentials and resolve chain-of-custody exceptions.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of records returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of records skipped and defaults to 0. Unless a workflow states otherwise, list results are ordered by `created_at` ascending. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources — rate cards, laboratories, drivers, vehicles, route templates, routes, stops, specimens, route exceptions, and run billings — carry a common set of system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that begins at creation and increments by one on every mutation. It underpins the optimistic-concurrency mechanism of §2.7.

One resource is deliberately leaner: a `ScanEvent` is an append-only chain-of-custody record and carries only `id` and `created_at`. A scan event has neither an `updated_at` nor a `version` field, because it is never modified after it is written.

### 2.5. Hierarchical Consistency and Nested Retrieval

Routes sit at the top of an aggregate that owns stops, specimens, route exceptions, and run billings; specimens in turn own their scan events. When a path names a nested resource, the server validates identifiers left to right and returns the first failure it meets: a scan against a stop under a non-existent route surfaces `ERR_ROUTE_NOT_FOUND` before the stop is ever examined, and a missing stop surfaces `ERR_STOP_NOT_FOUND`, a missing specimen `ERR_SPECIMEN_NOT_FOUND`, and so on for `ERR_DRIVER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_LAB_CLIENT_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, and `ERR_BILLING_NOT_FOUND`.

The platform frequently mutates more than one resource in a single operation, and it propagates state automatically rather than waiting for the client to poke each child. A driver's scan can drive a stop from one state to the next without a separate request against the stop; marking a stop missed cascades into the specimens it touches and opens exception records; completing a route settles its vehicle. Each such reconciliation independently mutates the affected resource — refreshing its `updated_at` and incrementing its `version` — so that a resource the client never named directly may still advance a version between reads. The specific cascades are described alongside the workflows that trigger them in §3.

### 2.6. Monetary and Scoring Precision

Every monetary amount in the system is an integer number of cents; there are no fractional cents. Wherever a charge multiplies a mileage figure or applies a percentage surcharge, the intermediate product is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway rounds up). Risk scores are likewise whole integers produced with round-half-up. Temperature readings are the one non-integer quantity: they are compared against a specimen's acceptable band to two decimal places, and the band's bounds are inclusive. The precise placement of each rounding step — in particular where the provisional and final route charges round differently — is specified in the workflows of §3, because that placement is what makes the two figures diverge.

### 2.7. Optimistic Concurrency Control

Generating a run billing for a route is guarded by an optimistic-concurrency check on the route. The billing-generation operation requires a non-optional `expected_route_version` field carrying the `version` of the target route as the client last observed it. If that value does not equal the route's current `version`, the operation is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because generating a billing legitimately supersedes any earlier draft and, as a side effect, advances the route's `version` by one; a client working from a `version` it read before an earlier billing was generated therefore no longer matches, and its create is refused as a stale-version write rather than silently overwriting a billing it never saw. No other endpoint accepts a version field; concurrency control applies only to billing generation.

### 2.8. Request Validation Order

When several conditions could reject a request, the server evaluates them in a fixed precedence and returns the first that fails, so that an earlier concern is never masked by a later one. The order is:

1. Authentication — headers present and `X-User-Role` known, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — the role is permitted for the operation and, for ownership-scoped roles, owns the target resource, else `ERR_UNAUTHORIZED` (403).
3. Existence — every path- and body-referenced resource exists, validated left to right, else the matching `ERR_*_NOT_FOUND` (404).
4. Body well-formedness — required fields present, enums in range, and the constraints in §3 satisfied, else `ERR_VALIDATION` (400).
5. Target state — the resource is in the state the transition requires, else the matching `ERR_*_INVALID_STATE` (409).
6. Optimistic concurrency — for billing generation, `expected_route_version` matches, else `ERR_STALE_VERSION` (412).
7. Then the business-safety, referential, constraint, and fiscal checks that guard individual workflows, each described where it applies: driver credential validity (`ERR_DRIVER_CREDENTIAL_INVALID`), credential-type sufficiency (`ERR_CREDENTIAL_TYPE_INSUFFICIENT`), vehicle refrigeration (`ERR_VEHICLE_REFRIGERATION_REQUIRED`), vehicle availability (`ERR_VEHICLE_NOT_AVAILABLE`), scan/stop matching (`ERR_SPECIMEN_STOP_MISMATCH`), driver schedule conflict (`ERR_DRIVER_SCHEDULE_CONFLICT`), vehicle sanitation buffer (`ERR_VEHICLE_BUFFER_CONFLICT`), route-has-stops (`ERR_ROUTE_HAS_NO_STOPS`), duplicate stop sequence (`ERR_DUPLICATE_STOP_SEQUENCE`), all-stops-resolved (`ERR_STOPS_NOT_RESOLVED`), and laboratory budget (`ERR_BUDGET_EXCEEDED`). Within this seventh tier the checks apply in the listed order, so that — for example — an invalid credential is reported before a credential-type shortfall, which is reported before a refrigeration shortfall, which is reported before the budget check.

### 2.9. The Logical Clock

Every reference to "now" in this document — credential expiry comparisons, scan and completion timestamps, sanitation-buffer arithmetic — reads a server-controlled logical clock rather than wall-clock time. An admin-only test-driving capability advances that clock to a supplied `to_iso8601` instant, after which all "now" reads use that value. Until it is first set, the clock reads exactly its startup default of `2026-05-01T00:00:00Z` and never falls back to wall-clock.

## 3. Business Logic & Workflows

### 3.1. Configuring the Courier Network

Before any run can move, a dispatcher assembles the reference data. A **rate card** is created with a human `name`, a `per_stop_fee_cents` charged per served stop, a `per_mile_rate_cents` charged per mile, a `stat_surcharge_pct` expressed as a fraction (for example, 0.30 for a thirty-percent uplift), a `stat_surcharge_cap_cents` ceiling on that surcharge, and a `temp_handling_fee_cents` added per temperature-controlled specimen. Each of the fee fields must be zero or greater, and the surcharge percentage must be zero or greater.

A **laboratory** — the ordering client — is created with a `name`, a `budget_cents` spending ceiling that must be zero or greater, and an optional `contact` string. Alongside these, each laboratory exposes a read-only `billed_balance_cents`: the sum of `net_charge_cents` across all of that laboratory's run billings currently in `ISSUED` status. Drafts and voided billings do not count toward it. This balance is the figure every budget gate consults.

A **driver** is created with a `name`, a `credential_type` of `STANDARD`, `BLOODBORNE`, or `HAZMAT`, and a `credential_expiry` instant after which the credential lapses; a credential is valid only while `credential_expiry` is strictly later than the current clock. A driver's `status` starts `ACTIVE` and may later become `SUSPENDED`. A **vehicle** is created with a `plate`, a `has_refrigeration` boolean, and an optional `sanitation_buffer_minutes` that defaults to 30 and must be zero or greater; its `status` starts `AVAILABLE` and toggles to `IN_USE` while committed to a run, and its `last_released_at` records the clock instant it was last freed by a route completion, remaining null until the first such release.

### 3.2. Building Routes: Recurring Templates and Manifests

Recurring lab work is captured as a **route template**. A dispatcher creates one against a `lab_client_id` and a `rate_card_id`, a `cadence` of `DAILY`, `WEEKDAYS`, or `WEEKLY`, a `default_run_type` of `STAT` or `SCHEDULED`, and a `stop_specs` array whose entries each carry a `sequence`, an `address`, a `stop_kind`, and a `planned_leg_miles`. Instantiating a run from a template creates a new route in `PLANNED` state with its `template_id` set to the source template, synthesizes one stop from each `stop_specs` entry, and computes the route's service-level deadline. The instantiation request supplies a `scheduled_start` and `scheduled_end`, and may supply a `run_type`; when `run_type` is omitted, the template's `default_run_type` applies.

A route may also be built directly. Creating one takes a `lab_client_id`, a `rate_card_id`, a `run_type` of `STAT` or `SCHEDULED`, a `scheduled_start`, a `scheduled_end`, and a `planned_total_miles` that must be zero or greater. The route begins in `PLANNED` state. Its `scheduled_end` must be strictly later than its `scheduled_start`; a body that violates this — or that omits a required field or carries an out-of-range enum — is rejected with `ERR_VALIDATION`. On creation the route's `sla_deadline` is computed: the deadline is the `scheduled_start` plus 120 minutes (two hours) for a `STAT` run, or plus 480 minutes (eight hours) for a `SCHEDULED` run. A route also carries system-managed `driver_id` and `vehicle_id` foreign keys, both null until assignment, and two computed money fields — `provisional_charge_cents` and `final_charge_cents` — that remain null until dispatch and completion respectively.

Stops and specimens are attached to a `PLANNED` route. Appending a **stop** supplies a `sequence` (a one-based ordinal that must be at least 1 and unique within the route), an `address`, a `stop_kind` of `PICKUP`, `DROPOFF`, or `BOTH`, and a `planned_leg_miles` for the leg arriving at that stop, which must be zero or greater. A `sequence` already used on the route is rejected with `ERR_DUPLICATE_STOP_SEQUENCE`. A stop begins in `SCHEDULED` state; its `actual_leg_miles`, `leg_charge_cents`, `arrived_at`, and `completed_at` are all system-managed and null until execution. Registering a **specimen** supplies a `pickup_stop_id`, a `dropoff_stop_id`, a `specimen_type` of `BLOOD`, `TISSUE`, `URINE`, `SWAB`, or `CULTURE`, a `temp_requirement` of `AMBIENT`, `REFRIGERATED`, or `FROZEN`, and an inclusive acceptable band given by `required_temp_min_c` and `required_temp_max_c`, where the maximum must be greater than or equal to the minimum (a body with the maximum below the minimum is rejected with `ERR_VALIDATION`). The specimen's owning `route_id` is set from the path. Its `custody_status` starts `AWAITING_PICKUP` and its `integrity_status` starts `INTACT`; these two dimensions evolve independently. Its `excursion_count` starts at zero, and its `picked_up_at`, `delivered_at`, `estimated_risk_score`, and `final_risk_score` are system-managed and null until the corresponding scans occur.

### 3.3. Crewing a Run: Assignment and Release

Assigning a route pairs it with a driver and a vehicle, supplied as `driver_id` and `vehicle_id`, and advances the route from `PLANNED` to `ASSIGNED`. The route must currently be `PLANNED`, else `ERR_ROUTE_INVALID_STATE`. The named driver and vehicle must exist. The driver must be `ACTIVE` and hold a credential whose `credential_expiry` is strictly later than the current clock, else `ERR_DRIVER_CREDENTIAL_INVALID`. The vehicle must be `AVAILABLE`, else `ERR_VEHICLE_NOT_AVAILABLE`. Two scheduling guards then apply. First, the driver must not already hold another route in `ASSIGNED` or `DISPATCHED` state whose planned window overlaps this route's window; the windows are treated as half-open intervals `[scheduled_start, scheduled_end)`, so a route that begins exactly when another ends does not conflict, but any true overlap is rejected with `ERR_DRIVER_SCHEDULE_CONFLICT`. Second, the vehicle must have cleared its sanitation gap: either its `last_released_at` is null, or this route's `scheduled_start` is at or later than `last_released_at` plus the vehicle's `sanitation_buffer_minutes`, else `ERR_VEHICLE_BUFFER_CONFLICT`. On success the route's `driver_id` and `vehicle_id` are set and the vehicle transitions `AVAILABLE → IN_USE`.

Releasing a route reverses this before it ever runs. Unassignment requires the route to be `ASSIGNED` (else `ERR_ROUTE_INVALID_STATE`), clears the route's `driver_id` and `vehicle_id`, and returns the vehicle `IN_USE → AVAILABLE`. Because the run never executed, `last_released_at` is deliberately left unchanged — an unassignment must not open a fresh sanitation window.

### 3.4. Dispatch: Safety Gates and the Provisional Charge

Dispatching advances a route from `ASSIGNED` to `DISPATCHED` and is where the platform's compliance gates concentrate. The route must be `ASSIGNED`, else `ERR_ROUTE_INVALID_STATE`. It must carry at least one stop, else `ERR_ROUTE_HAS_NO_STOPS`. The driver's credential is re-checked exactly as at assignment — `ACTIVE` and `credential_expiry` strictly later than the current clock — because it may have lapsed or the driver been suspended in the interim, else `ERR_DRIVER_CREDENTIAL_INVALID`. The driver's `credential_type` must be sufficient for every specimen aboard: a `CULTURE` specimen requires `BLOODBORNE` or `HAZMAT`, and any specimen whose `temp_requirement` is `FROZEN` requires `HAZMAT`; a shortfall is rejected with `ERR_CREDENTIAL_TYPE_INSUFFICIENT`. If any specimen requires `REFRIGERATED` or `FROZEN` handling, the assigned vehicle's `has_refrigeration` must be true, else `ERR_VEHICLE_REFRIGERATION_REQUIRED`.

Dispatch then computes the route's `provisional_charge_cents` and applies the budget gate. The provisional charge is assembled from three subtotals over the whole planned manifest. The stop subtotal is `per_stop_fee_cents` multiplied by the count of every stop on the route, regardless of state. The mileage subtotal is `planned_total_miles` multiplied by `per_mile_rate_cents`, with that single product rounded half-up to whole cents. The temperature subtotal is `temp_handling_fee_cents` multiplied by the number of specimens whose `temp_requirement` is anything other than `AMBIENT`. Summing the three yields the base. On a `STAT` run a surcharge is added equal to the base multiplied by `stat_surcharge_pct`, rounded half-up to whole cents, then capped so the surcharge is the smaller of that rounded amount and `stat_surcharge_cap_cents`; on a `SCHEDULED` run the surcharge is zero. `provisional_charge_cents` is the base plus the surcharge. The budget gate then requires that the owning laboratory's `billed_balance_cents` plus this provisional charge not exceed its `budget_cents`, else `ERR_BUDGET_EXCEEDED`.

### 3.5. On the Road: Scans, Chain of Custody, and Temperature Integrity

Only the assigned driver executes the run, and only through scans. Recording a scan against a stop supplies a `specimen_id`, a `scan_type` of `PICKUP` or `DROPOFF`, a `temp_reading_c`, and the `leg_miles` odometer reading for the leg reaching that stop; the resulting `ScanEvent` records the acting driver's identity in `driver_id`, the `stop_id`, and the `scanned_at` clock instant. Scans are permitted only while the parent route is `DISPATCHED` (else `ERR_ROUTE_INVALID_STATE`), and only when the acting driver's own identity matches the route's `driver_id` (else `ERR_UNAUTHORIZED`). The first scan at a stop moves it `SCHEDULED → ARRIVED`, stamping its `arrived_at` with the current clock and recording that first scan's `leg_miles` as the stop's `actual_leg_miles`; subsequent scans at the same stop leave `actual_leg_miles` untouched.

A pickup scan advances the specimen's custody dimension `AWAITING_PICKUP → IN_TRANSIT`. The specimen must currently be `AWAITING_PICKUP`, else `ERR_SPECIMEN_INVALID_STATE`, and the scanned stop must be the specimen's own `pickup_stop_id`, else `ERR_SPECIMEN_STOP_MISMATCH`. The scan stamps `picked_up_at` and computes the specimen's `estimated_risk_score`. That estimate begins from a base determined by `specimen_type` — 10 for `BLOOD`, 20 for `TISSUE`, 5 for `URINE`, 5 for `SWAB`, and 15 for `CULTURE` — to which is added the planned transit duration in minutes (the route's `scheduled_end` minus its `scheduled_start`) divided by ten and rounded half-up. A dropoff scan advances the specimen `IN_TRANSIT → DELIVERED`; the specimen must be `IN_TRANSIT` (else `ERR_SPECIMEN_INVALID_STATE`) and the scanned stop must be its `dropoff_stop_id` (else `ERR_SPECIMEN_STOP_MISMATCH`). The dropoff stamps `delivered_at` and computes the `final_risk_score` from the same `specimen_type` base plus the realized transit duration in minutes (`delivered_at` minus `picked_up_at`) divided by ten and rounded half-up, plus a penalty of 25 points for each temperature excursion the specimen has accumulated in `excursion_count`.

Every scan, pickup or dropoff, is evaluated for a temperature excursion. The reading is an excursion when `temp_reading_c` is strictly below the specimen's `required_temp_min_c` or strictly above its `required_temp_max_c`, compared to two decimal places; a reading exactly equal to either bound is in band and is not an excursion. The scan event records this outcome in its `is_excursion` flag. When an excursion occurs, the specimen's integrity dimension moves `INTACT → COMPROMISED`, its `excursion_count` is incremented by one, and a route exception of type `TEMP_EXCURSION` is opened. Because custody and integrity are independent, a specimen can reach `DELIVERED` while `COMPROMISED`; the delivery is recorded but the integrity breach travels with it.

Delivering a specimen also re-evaluates its dropoff stop. A stop in `ARRIVED` state advances `ARRIVED → COMPLETED` once every specimen whose `pickup_stop_id` is that stop has left `AWAITING_PICKUP`, and every specimen whose `dropoff_stop_id` is that stop has reached `DELIVERED`. On completion the stop stamps `completed_at` and computes its `leg_charge_cents` as `per_stop_fee_cents` plus the product of its `actual_leg_miles` and `per_mile_rate_cents` rounded half-up to whole cents.

### 3.6. Missed Stops, Exceptions, and Credential Governance

A stop that cannot be served is marked missed, an action available to the driver or the dispatcher. The parent route must be `DISPATCHED` (else `ERR_ROUTE_INVALID_STATE`); a stop may be missed from either `SCHEDULED` or `ARRIVED`, and any other stop state is rejected with `ERR_STOP_INVALID_STATE`. Marking a stop missed drives it to `MISSED` and cascades in two linked steps. First, every specimen whose `pickup_stop_id` or `dropoff_stop_id` is this stop and whose `custody_status` is `AWAITING_PICKUP` or `IN_TRANSIT` is moved to custody `EXCEPTION`, removing it from the deliverable set. Second, each such implicated specimen opens one route exception of type `MISSED_STOP`, in `OPEN` status, carrying the `route_id`, the `stop_id`, and that `specimen_id`. If the missed stop implicated no specimens at all, a single `MISSED_STOP` exception is still opened with the `route_id` and `stop_id` set and `specimen_id` left null. Every route exception also carries a system-generated `detail` describing the event.

A missed stop may be rescheduled by a dispatcher, moving it `MISSED → SCHEDULED`; the stop must currently be `MISSED`, else `ERR_STOP_INVALID_STATE`. Rescheduling clears the stop's `arrived_at` so the revision cycle can begin cleanly. A compliance officer resolves an open exception, moving it `OPEN → RESOLVED`; the exception must be `OPEN`, else `ERR_EXCEPTION_INVALID_STATE`. Once `RESOLVED` an exception is terminal, and the resolution captures an optional `resolution_note` into the exception. Beyond `MISSED_STOP` and `TEMP_EXCURSION`, the `exception_type` enumeration also includes `CREDENTIAL_LAPSE`.

Driver credentials are governed exclusively by compliance officers through a single credential operation that carries an `action`. A `SUSPEND` action drives an `ACTIVE` driver `ACTIVE → SUSPENDED`, after which the driver is treated as credential-invalid on any subsequent assignment or dispatch. A `REINSTATE` action returns a `SUSPENDED` driver `SUSPENDED → ACTIVE`. A `RENEW` action leaves an `ACTIVE` driver `ACTIVE` and sets its `credential_expiry` to the supplied `credential_expiry`. Each action requires the driver to be in the matching starting state, else `ERR_DRIVER_INVALID_STATE`.

### 3.7. Completing the Run and the Final Charge

A route is completed by a dispatcher, moving it `DISPATCHED → COMPLETED`. The route must be `DISPATCHED`, else `ERR_ROUTE_INVALID_STATE`, and every stop on the route must have settled into either `COMPLETED` or `MISSED`; if any stop is still unresolved the completion is rejected with `ERR_STOPS_NOT_RESOLVED`. Completion computes the route's `final_charge_cents`, and this is where the final figure diverges from the provisional one: rather than rounding the whole route's mileage once, the final charge rounds each served leg independently and then sums.

The system processes only the route's `COMPLETED` stops — stops that ended `MISSED` are excluded — ordered by `sequence` ascending, breaking any tie by `created_at` ascending. Each such stop contributes its `leg_charge_cents`, equal to `per_stop_fee_cents` plus the product of that stop's `actual_leg_miles` and `per_mile_rate_cents` rounded half-up to whole cents. The leg-and-stop subtotal is the sum of those already-rounded per-leg charges. A final temperature subtotal is `temp_handling_fee_cents` multiplied by the number of specimens whose `temp_requirement` is other than `AMBIENT` and whose `custody_status` is `DELIVERED`. Their sum is the final base. On a `STAT` run the final surcharge is the base multiplied by `stat_surcharge_pct`, rounded half-up and capped at `stat_surcharge_cap_cents`; on a `SCHEDULED` run it is zero. `final_charge_cents` is the final base plus its surcharge. Because the provisional charge rounds the planned mileage once while the final charge rounds each completed leg before summing, the two figures diverge whenever per-leg rounding and whole-route rounding differ, and they also diverge whenever stops were missed or temperature specimens went undelivered. On completion the vehicle is returned `IN_USE → AVAILABLE` and its `last_released_at` is set to the current clock, opening its next sanitation window.

### 3.8. Billing the Laboratory

Once a route is complete a dispatcher generates its **run billing**, a create that snapshots the settled charge and is guarded by the optimistic-concurrency check of §2.7. The request carries `expected_route_version`, which must equal the route's current `version`, else `ERR_STALE_VERSION`. A generated billing captures its `route_id` and `lab_client_id` and snapshots three amounts from the route's final charge: `gross_charge_cents`, the pre-surcharge final base; `surcharge_cents`, the STAT surcharge component, which is zero on a `SCHEDULED` run; and `net_charge_cents`, their sum, which equals the route's `final_charge_cents`. The new billing begins in `DRAFT` status, and generating it advances the route's `version` by one, which is precisely why a second generation working from a stale `expected_route_version` is refused — an earlier generation legitimately supersedes any prior draft.

Issuing a draft billing moves it `DRAFT → ISSUED` and debits the laboratory. The billing must be `DRAFT`, else `ERR_BILLING_INVALID_STATE`, and the laboratory's `billed_balance_cents` plus this billing's `net_charge_cents` must not exceed its `budget_cents`, else `ERR_BUDGET_EXCEEDED`; on success the laboratory's `billed_balance_cents` rises by `net_charge_cents`. Voiding an issued billing moves it `ISSUED → VOIDED` and reverses the debit. The billing must be `ISSUED`, else `ERR_BILLING_INVALID_STATE`; on success the laboratory's `billed_balance_cents` falls by `net_charge_cents`, restoring the conserved total. Because `billed_balance_cents` is defined as the sum of `net_charge_cents` across only the laboratory's `ISSUED` billings, a `DRAFT` billing exerts no pressure on the budget until it is issued, and a `VOIDED` one exerts none thereafter.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including the lifecycle transitions that assign, dispatch, complete, scan, miss, reschedule, resolve, issue, or void — return `200 OK`. Reconstructing the full request and response for any endpoint requires reading the §3 workflow that governs it; this table is intentionally limited to routing and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/med-courier/rate-cards` | Create a rate card | Dispatcher |
| GET | `/med-courier/rate-cards/{id}` | Fetch a rate card | Dispatcher, ComplianceOfficer, LabClient |
| POST | `/med-courier/lab-clients` | Create a lab client | Dispatcher |
| GET | `/med-courier/lab-clients/{id}` | Fetch a lab client | Dispatcher, ComplianceOfficer, LabClient |
| POST | `/med-courier/drivers` | Create a driver | Dispatcher, ComplianceOfficer |
| GET | `/med-courier/drivers/{id}` | Fetch a driver | Dispatcher, ComplianceOfficer |
| POST | `/med-courier/drivers/{id}/credential` | Renew, suspend, or reinstate a driver credential | ComplianceOfficer |
| POST | `/med-courier/vehicles` | Create a vehicle | Dispatcher |
| GET | `/med-courier/vehicles/{id}` | Fetch a vehicle | Dispatcher, ComplianceOfficer |
| POST | `/med-courier/route-templates` | Create a recurring lab-route template | Dispatcher |
| GET | `/med-courier/route-templates` | List route templates | Dispatcher, LabClient |
| GET | `/med-courier/route-templates/{id}` | Fetch a route template | Dispatcher, LabClient |
| POST | `/med-courier/route-templates/{id}/generate-route` | Instantiate a route (and its stops) from a template | Dispatcher |
| POST | `/med-courier/routes` | Create a route | Dispatcher, LabClient |
| GET | `/med-courier/routes` | List routes | Dispatcher, ComplianceOfficer, LabClient |
| GET | `/med-courier/routes/{id}` | Fetch a route | Dispatcher, ComplianceOfficer, LabClient, Driver |
| POST | `/med-courier/routes/{id}/stops` | Append a stop to a route | Dispatcher, LabClient |
| POST | `/med-courier/routes/{id}/specimens` | Register a specimen on a route | Dispatcher, LabClient |
| POST | `/med-courier/routes/{id}/assign` | Assign driver and vehicle | Dispatcher |
| POST | `/med-courier/routes/{id}/unassign` | Release driver and vehicle | Dispatcher |
| POST | `/med-courier/routes/{id}/dispatch` | Dispatch a route | Dispatcher |
| POST | `/med-courier/routes/{id}/complete` | Complete a route | Dispatcher |
| POST | `/med-courier/routes/{id}/billing` | Generate a run billing for a completed route | Dispatcher |
| GET | `/med-courier/stops` | List stops | Dispatcher, ComplianceOfficer, LabClient, Driver |
| GET | `/med-courier/stops/{id}` | Fetch a stop | Dispatcher, ComplianceOfficer, LabClient, Driver |
| POST | `/med-courier/stops/{id}/scan` | Record a pickup or dropoff scan | Driver |
| POST | `/med-courier/stops/{id}/miss` | Mark a stop missed | Driver, Dispatcher |
| POST | `/med-courier/stops/{id}/reschedule` | Reschedule a missed stop | Dispatcher |
| GET | `/med-courier/specimens` | List specimens | Dispatcher, ComplianceOfficer, LabClient, Driver |
| GET | `/med-courier/specimens/{id}` | Fetch a specimen | Dispatcher, ComplianceOfficer, LabClient, Driver |
| GET | `/med-courier/scan-events` | List chain-of-custody scan events | Dispatcher, ComplianceOfficer, LabClient, Driver |
| GET | `/med-courier/scan-events/{id}` | Fetch a scan event | Dispatcher, ComplianceOfficer, LabClient, Driver |
| GET | `/med-courier/exceptions` | List route exceptions | Dispatcher, ComplianceOfficer, LabClient |
| GET | `/med-courier/exceptions/{id}` | Fetch a route exception | Dispatcher, ComplianceOfficer, LabClient |
| POST | `/med-courier/exceptions/{id}/resolve` | Resolve an open exception | ComplianceOfficer |
| GET | `/med-courier/billings` | List run billings | Dispatcher, ComplianceOfficer, LabClient |
| GET | `/med-courier/billings/{id}` | Fetch a run billing | Dispatcher, ComplianceOfficer, LabClient |
| POST | `/med-courier/billings/{id}/issue` | Issue a draft billing | Dispatcher |
| POST | `/med-courier/billings/{id}/void` | Void an issued billing | Dispatcher |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_STOP_NOT_FOUND` | 404 |
| `ERR_SPECIMEN_NOT_FOUND` | 404 |
| `ERR_DRIVER_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_LAB_CLIENT_NOT_FOUND` | 404 |
| `ERR_RATE_CARD_NOT_FOUND` | 404 |
| `ERR_TEMPLATE_NOT_FOUND` | 404 |
| `ERR_EXCEPTION_NOT_FOUND` | 404 |
| `ERR_BILLING_NOT_FOUND` | 404 |
| `ERR_ROUTE_INVALID_STATE` | 409 |
| `ERR_STOP_INVALID_STATE` | 409 |
| `ERR_SPECIMEN_INVALID_STATE` | 409 |
| `ERR_BILLING_INVALID_STATE` | 409 |
| `ERR_EXCEPTION_INVALID_STATE` | 409 |
| `ERR_DRIVER_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DRIVER_CREDENTIAL_INVALID` | 422 |
| `ERR_CREDENTIAL_TYPE_INSUFFICIENT` | 422 |
| `ERR_VEHICLE_REFRIGERATION_REQUIRED` | 422 |
| `ERR_VEHICLE_NOT_AVAILABLE` | 409 |
| `ERR_DRIVER_SCHEDULE_CONFLICT` | 409 |
| `ERR_VEHICLE_BUFFER_CONFLICT` | 409 |
| `ERR_ROUTE_HAS_NO_STOPS` | 422 |
| `ERR_DUPLICATE_STOP_SEQUENCE` | 409 |
| `ERR_SPECIMEN_STOP_MISMATCH` | 422 |
| `ERR_STOPS_NOT_RESOLVED` | 409 |
| `ERR_BUDGET_EXCEEDED` | 402 |
