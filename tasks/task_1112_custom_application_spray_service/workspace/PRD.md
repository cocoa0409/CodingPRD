# Custom Spray Service API — Product Requirements Document

## 1. Introduction

Agricultural co-ops run custom application crews the way airlines run fleets: every job is a regulated event. A grower calls in a work order against a field and a product prescription; a licensed applicator drives a calibrated sprayer through a narrow weather window; and every gallon sprayed, every rinsate drop disposed, and every drift complaint filed leaves a paper trail that regulators, insurers, and neighbors can demand to see years later. Mistakes are not merely expensive — an out-of-envelope application can void a license, contaminate an organic neighbor, or trigger litigation.

This document specifies the Custom Spray Service API, the system of record for one such co-op's custom applicator operation. The API governs the full arc of a spray job: registry data (grower accounts, fields, the product catalog, and tank-mix compatibility rulings), agronomist prescriptions and their seasonal authority, applicator licensing and equipment calibration discipline, work order scheduling under a gauntlet of safety and fiscal gates, in-field execution gated on weather observations and re-entry intervals, post-job record certification under segregation of duties, rinsate disposal accounting, drift complaint investigation with an automatic disciplinary cascade, and per-acre billing with product markup under a customer credit limit. All resources are served under the `/api` mount.

The design follows two guiding commitments. First, compliance is not advisory: safety gates reject work rather than warn about it, and disciplinary state changes propagate automatically through the schedule. Second, money and chemistry are reconciled in two variants — provisional figures computed from prescribed rates at booking and completion, and final figures computed from certified actual rates once the application record clears compliance review.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request whose `X-User-Role` header names no declared role, or whose `X-User-ID` header is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes six roles, spelled exactly as follows: `Grower`, `Agronomist`, `Dispatcher`, `Applicator`, `ComplianceOfficer`, and `CoopAdmin`. Access to each operation is restricted by role, and a caller whose role is not authorized for an endpoint — or who fails an ownership or assignment check on the target — is rejected with `ERR_FORBIDDEN` (HTTP 403). One further authorization rule is specific enough to stand alone: certification of an application record enforces segregation of duties, and a certifier whose `X-User-ID` equals the record's performing `applicator_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer — a field's `customer_id`, a work order's `customer_id`, a complaint's `complainant_customer_id`, or the customer reached through an invoice's work order — compare the resource's foreign-key field to `X-User-ID`. A `Grower` may therefore create fields and work orders only for their own `customer_id`, cancel only their own work orders, pay only invoices belonging to their own account, and read only their own customer record. When `X-User-Role` is `Applicator`, `X-User-ID` is the `id` of the acting Applicator; assignment checks compare a work order's `applicator_id` (or an application record's `applicator_id`) to `X-User-ID`, so an applicator may start, resume, or complete only work assigned to them, and may resubmit only their own returned records.

The remaining four roles are opaque. When `X-User-Role` is `Agronomist`, `Dispatcher`, `ComplianceOfficer`, or `CoopAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on a Prescription, as `recorded_by_user_id` on a WeatherObservation, or as `certified_by_user_id` on an ApplicationRecord — but it does not compare the value to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The weather observation feed is the documented exception: it returns observations newest-first by `observed_at`.

Paginated list responses carry four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Common Properties

Every resource in the system carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp recording when the resource was first persisted. Timestamps throughout the API are ISO 8601 UTC strings with three fractional digits.

Most resources are mutable and therefore also carry `updated_at`, refreshed on every mutation, and `version`, an integer that increments by one on every mutation to the resource. The resources carrying the full four-field set are: Customer, Field, Product, Prescription, Applicator, Equipment, WorkOrder, ApplicationRecord, DriftComplaint, and Invoice. Four resources are append-only evidence records and carry only `id` and `created_at`: CompatibilityRule, CalibrationRecord, WeatherObservation, and RinsateRecord. On those four, both `updated_at` and `version` are absent.

Mutations caused by cascades count the same as direct mutations: any time a cascade touches a resource, that resource's `updated_at` refreshes and its `version` increments, independently of whatever other resources the same cascade touches.

### 2.5. Logical Time

The server runs on a logical clock rather than wall-clock time, so that time-sensitive rules are reproducible. Before any call to set it, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never silently falls back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc` value.

Everywhere this document says "the current time" or "now" — scheduling windows, observation freshness, license expiry at start, the complaint filing window — it means the logical clock. System-stamped datetimes such as `performed_at` on a calibration record, `recorded_at` on a rinsate record, and `started_at` / `completed_at` on a work order are all taken from the logical clock at the moment the operation executes.

### 2.6. Units, Money, and Rounding Conventions

Money is handled in integer cents everywhere: customer rates and credit limits, product costs, and every invoice amount. Invoice mathematics rounds half-up to whole cents, and the rounding order is pinned: each product line of an invoice is rounded to whole cents first, the lines are then summed, and the service fee is rounded independently of the lines. Summing raw values and rounding once at the end is a different, non-conforming algorithm.

Three other numeric conventions apply. Calibration error percentages are rounded half-up to exactly 2 decimal places. Rinsate volumes are rounded half-up to exactly 1 decimal place. Weather readings — wind speed and temperature — are compared exactly as given, with no rounding at all. Datetimes are compared to the second. Penalty points on applicators are whole-number integers.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and both reject a stale client view rather than silently overwriting it.

Approving a prescription requires the request to carry `expected_field_version`, a non-optional input holding the version of the prescription's parent Field as the agronomist last observed it. If `expected_field_version` does not equal the Field's current `version` — for example because another approval for the same field and season has just superseded the previously approved prescription and advanced the field's version — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). This is purely a stale-version check on the Field; the rule exists so a writer never approves against a field whose governing prescription has moved under them.

Rescheduling a work order requires the request to carry `expected_work_order_version`, a non-optional input holding the work order's `version` as the dispatcher last observed it. Amending a `SCHEDULED` work order is legitimate any number of times, so a second reschedule cannot be refused on state grounds; instead, if the supplied value does not match the work order's current `version`, the reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412) purely because the client's observed version is stale.

No endpoint other than these two takes a version field of any kind.

### 2.8. Cascading Reconciliation Across the Operation

Several events in this domain are never isolated. When an underlying fact changes — a complaint is substantiated, a sprayer fails calibration, a new prescription wins approval — the server reconciles every dependent resource automatically, without waiting for a client request on each one. Each reconciliation independently mutates the resources it touches: every affected work order, applicator, sprayer, prescription, invoice, or customer has its own `updated_at` refreshed and its own `version` incremented.

Three cascades anchor the design. Approving a prescription for a field and season that already has an approved prescription retires the older one. A failed calibration — or an applicator sliding into suspension or revocation — strips the affected resource from the future schedule by reverting each of its `SCHEDULED` work orders to `DRAFT`, clearing `applicator_id`, `equipment_id`, `scheduled_start`, and `scheduled_end`, resetting `uses_adjuvant` to false, and nulling `estimated_total_cents`. Substantiating a drift complaint is the deepest cascade of all: it lands penalty points on the applicator, may suspend or revoke their license, pulls their scheduled work back to draft, and voids the complained work order's invoice with a credit back to the grower's balance. The business narratives in §3 give each cascade in full.

### 2.9. Validation Precedence

When several checks could reject the same request, the server evaluates them in a fixed precedence order so the reported failure is deterministic. The order is:

1. **Authentication** — the `X-User-Role` header names a declared role and `X-User-ID` is present, else `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the role is permitted on the endpoint, and ownership or assignment checks hold (a `Grower` acting only for their own `customer_id`; an `Applicator` acting only on work assigned to them), else `ERR_FORBIDDEN`.
3. **Segregation of duties on certification** — the certifier differs from the performing applicator, else `ERR_SEGREGATION_OF_DUTIES`.
4. **Body shape** — required fields present, types valid, enum members valid, numbers positive where required, else `ERR_VALIDATION`.
5. **Existence** — path identifiers and body foreign-key references exist, else `ERR_NOT_FOUND`.
6. **State** — the target resource is in a valid from-state for the requested transition, and linked-entity state preconditions hold (prescription approved, applicator active, record certified), surfacing as `ERR_INVALID_STATE`, `ERR_PRESCRIPTION_NOT_APPROVED`, `ERR_APPLICATOR_NOT_ACTIVE`, `ERR_RECORD_NOT_CERTIFIED`, or `ERR_INVESTIGATION_PENDING`.
7. **Regulatory safety gates** — re-entry lockout, weather envelope and freshness, license validity and category coverage, buffer clearance, tank-mix compatibility and adjuvant, surfacing as `ERR_REI_ACTIVE`, `ERR_WEATHER_WINDOW_VIOLATION`, `ERR_OBSERVATION_STALE`, `ERR_LICENSE_EXPIRED`, `ERR_LICENSE_CATEGORY_MISSING`, `ERR_BUFFER_VIOLATION`, `ERR_INCOMPATIBLE_TANK_MIX`, or `ERR_ADJUVANT_REQUIRED`.
8. **Temporal windows and interval conflicts** — prescription windows, field and applicator overlap, the calibration validity horizon, and the complaint filing window, surfacing as `ERR_OUTSIDE_APPLICATION_WINDOW`, `ERR_FIELD_TIME_CONFLICT`, `ERR_APPLICATOR_TIME_CONFLICT`, `ERR_CALIBRATION_OVERDUE`, or `ERR_COMPLAINT_WINDOW_CLOSED`.
9. **Domain constraints** — the acreage cap, rinsate accounting, disposal-field match, complaint holds on invoicing, duplicate open complaints, and invoice settlement before close, surfacing as `ERR_ACREAGE_EXCEEDED`, `ERR_RINSATE_BALANCE_OPEN`, `ERR_RINSATE_OVER_DISPOSAL`, `ERR_DISPOSAL_FIELD_MISMATCH`, `ERR_COMPLAINT_HOLD`, `ERR_DUPLICATE_OPEN_COMPLAINT`, or `ERR_INVOICE_UNSETTLED`.
10. **Fiscal limit** — outstanding balance plus the prospective amount must stay within the customer's credit limit, else `ERR_CREDIT_LIMIT_EXCEEDED`.

The practical consequence: a request that is both unauthenticated and malformed fails as unauthenticated; a scheduling request against a non-existent sprayer fails with `ERR_NOT_FOUND` before any safety gate runs; and a credit-limit breach is only ever reported after every safety, temporal, and domain constraint has passed.

### 2.10. Grower Credit and the Outstanding Balance Ledger

Each Customer carries a credit account. `credit_limit_cents` is the maximum outstanding invoice balance the co-op will tolerate, and `outstanding_cents` is the running balance — at any moment it equals the sum of `final_amount_cents` over that customer's invoices currently in `ISSUED` status. Issuing an invoice debits the balance by its `final_amount_cents`; paying an issued invoice credits it back; voiding an issued invoice credits it back as well. Voiding a `DRAFT` invoice changes nothing, because a draft was never part of the sum. The balance starts at zero when the customer is created and moves only through these invoice events.

The credit limit is enforced prospectively at two points: when a work order is scheduled, the customer's `outstanding_cents` plus the job's `estimated_total_cents` must stay within `credit_limit_cents`; and when an invoice is issued, `outstanding_cents` plus the invoice's `final_amount_cents` must stay within the same limit. A breach at either point is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

## 3. Business Logic & Workflows

### 3.1. The Registry: Customers, Fields, Products, and Compatibility Rulings

Everything begins with the registry, maintained by a `CoopAdmin`. Onboarding a grower means creating a Customer with a `name`, a `billing_email` for invoice delivery, a contracted `rate_per_acre_cents` — the application service fee per treated acre, in cents — and a `credit_limit_cents`. The new account's `outstanding_cents` starts at zero and changes only through the invoice events described in §2.10.

Fields belong to growers. A `Grower` may register a field only for their own account — the payload's `customer_id` must equal the caller's `X-User-ID` — while a `CoopAdmin` may register one for any customer. Each field records a human `label` such as "North 40", the `crop` under treatment, its total `acres`, and `buffer_clearance_ft`, the measured distance in feet from the field boundary to the nearest sensitive area (a waterway, a school, an organic neighbor). A fresh field has `rei_until` null, meaning no re-entry lockout has ever been set on it; §3.5 explains how completions move that value.

The product catalog holds one Product per trade name, each with its `epa_registration_no` from the label, a `category` of `HERBICIDE`, `INSECTICIDE`, or `FUNGICIDE`, and the label constraints that later gate scheduling and execution: `rei_hours` (the re-entry interval after application), `max_wind_mph`, `min_temp_f`, `max_temp_f`, and `required_buffer_ft` (the label-required downwind buffer to sensitive areas). Pricing comes from `unit_cost_cents`, the co-op's cost per gallon, and `markup_pct`, the percentage applied on top of cost when billing — a value of 15 means fifteen percent.

Between products sit the co-op's tank-mix rulings. A `CoopAdmin` declares a CompatibilityRule for an unordered pair of products via `product_a_id` and `product_b_id`, with a `verdict` of `COMPATIBLE`, `CONDITIONAL`, or `INCOMPATIBLE` and an optional free-text `note` carrying any label commentary. At most one rule may exist per unordered pair — declaring a pair that already has a ruling, in either order, is rejected with `ERR_VALIDATION` — and a pair with no rule at all is treated as `COMPATIBLE`. A `CONDITIONAL` verdict means the pair may run only when the work order's tank mix includes the required adjuvant, signaled by `uses_adjuvant`; that coupling bites at scheduling time in §3.4. Compatibility rules are evidence records: once declared, they carry no `updated_at` or `version`.

### 3.2. Prescriptions and Season Authority

An `Agronomist` authors a Prescription for a field and season, supplying the `field_id`, the `season_year`, an application window `valid_from` and `valid_to` (both inclusive — a scheduled job must open no earlier than `valid_from` and close no later than `valid_to`), the `carrier_gpa` (total carrier volume, water plus product, per acre in gallons — the figure that later drives load counts and rinsate math), and the `lines`: an array of entries each pairing a `product_id` with its prescribed `rate_per_acre`, forming the prescribed product set, in which each product appears at most once and every `rate_per_acre` is positive. A new prescription is born `DRAFT`, and the server stamps `created_by_user_id` with the author's `X-User-ID` — an opaque operator id, not an entity reference.

Approval turns a draft into the field's governing document, and it is deliberately serialized. The approval request must carry `expected_field_version` equal to the field's current `version`; a mismatch means the agronomist's view of the field is stale — typically because a competing prescription for the same field and season was just approved — and the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). Two label gates then run: every line product's `required_buffer_ft` must be no greater than the field's `buffer_clearance_ft` (else `ERR_BUFFER_VIOLATION`), and no pair of lines may carry a verdict of `INCOMPATIBLE` (else `ERR_INCOMPATIBLE_TANK_MIX`).

Approval carries three side effects. Any other `APPROVED` prescription for the same field and `season_year` is automatically moved to `SUPERSEDED` — there is at most one approved prescription per field per season, and `DRAFT` prescriptions are never auto-superseded, so only the single approved one is replaced. The Field's `version` increments by one, because approval changes the field's governing prescription. And the Prescription's own `version` increments by one. A superseded prescription is terminal; a `DRAFT` that never wins approval simply stays a draft.

### 3.3. People and Machines: Licensing, Calibration, and Reinstatement

A `CoopAdmin` registers each spray operator as an Applicator with a `display_name`, a state `license_no`, a `license_expires_on` instant, and `license_categories` — the array of product categories (`HERBICIDE`, `INSECTICIDE`, `FUNGICIDE`) the license covers. New applicators start `ACTIVE` with `penalty_points_lifetime` and `rolling_score_365` both zero. A license is valid for a job only if `license_expires_on` is on or after the job's `scheduled_end`; §3.8 explains how complaints move an applicator from `ACTIVE` to `SUSPENDED` and ultimately `REVOKED`, the terminal state.

Sprayers are registered as Equipment with a `unit_label` such as "Sprayer-1" and a `tank_capacity_gal`. New equipment starts `AVAILABLE` with `calibration_valid_until` null — uncalibrated, and therefore not yet schedulable.

Calibration is a measurement ritual. An `Applicator` posts a calibration record for a sprayer with `equipment_id`, `target_gpa`, and `measured_gpa`; the server takes `applicator_id` from the caller's `X-User-ID`. A `CoopAdmin` may post a record on an applicator's behalf but must then supply `applicator_id` explicitly in the payload. The record's `performed_at` is the logical clock at creation. From the two flow figures the server computes `error_pct`: the absolute difference between `measured_gpa` and `target_gpa`, divided by `target_gpa`, multiplied by 100, rounded half-up to two decimal places. The `verdict` is `PASS` when `error_pct` is at most 5.0 — exactly 5.0 passes — and `FAIL` otherwise.

The verdict moves the machine. On a `PASS`, the equipment's `calibration_valid_until` becomes `performed_at` plus 180 days and the equipment is `AVAILABLE`; a `PASS` posted while the unit is already `AVAILABLE` simply extends the validity horizon, and in both cases the Equipment's `version` increments. A `PASS` also lifts a `CALIBRATION_DUE` unit back to `AVAILABLE`. On a `FAIL`, the equipment drops to `CALIBRATION_DUE` and `calibration_valid_until` is left unchanged — a failure never shortens or extends the prior validity. The failure then cascades: every `SCHEDULED` work order naming that sprayer reverts to `DRAFT` with its assignment cleared, as §2.8 describes. Calibration records are evidence: like compatibility rules, they carry no `updated_at` or `version`.

A suspended applicator returns to duty only through a `ComplianceOfficer`'s reinstatement, which moves `SUSPENDED` back to `ACTIVE` and increments the Applicator's `version`. Reinstatement is blocked while any drift complaint naming that applicator is still `INVESTIGATING` — the attempt is rejected with `ERR_INVESTIGATION_PENDING` — because the co-op does not restore a license mid-inquiry.

### 3.4. Booking the Job: Work Order Intake and the Scheduling Gauntlet

A work order is born when a `Grower` — again, only for their own `customer_id` — or a `Dispatcher` acting on a grower's behalf creates one with a `customer_id`, a `field_id`, the governing `prescription_id`, and the `acres_to_treat`. The acreage must be positive (a non-positive value is a body-shape failure, `ERR_VALIDATION`) and may not exceed the field's total `acres` — overshooting the field is rejected with `ERR_ACREAGE_EXCEEDED`. A new work order is `DRAFT`: `applicator_id`, `equipment_id`, `scheduled_start`, and `scheduled_end` are all null until scheduling, `uses_adjuvant` defaults to false, `started_at` and `completed_at` are null, `estimated_total_cents` is null while the order remains a draft, and both rinsate counters start at zero.

Scheduling is the gauntlet, run by a `Dispatcher` with a payload of `applicator_id`, `equipment_id`, `scheduled_start`, `scheduled_end`, and an optional `uses_adjuvant`. Every gate below must pass before the order moves from `DRAFT` to `SCHEDULED`:

- The referenced prescription must be `APPROVED`, else `ERR_PRESCRIPTION_NOT_APPROVED`.
- The named applicator must exist and be `ACTIVE`, else `ERR_APPLICATOR_NOT_ACTIVE`.
- The applicator's `license_expires_on` must be on or after `scheduled_end`, else `ERR_LICENSE_EXPIRED`.
- The applicator's `license_categories` must cover every product `category` appearing in the prescription's lines, else `ERR_LICENSE_CATEGORY_MISSING`.
- Every line product's `required_buffer_ft` must fit within the field's `buffer_clearance_ft`, else `ERR_BUFFER_VIOLATION`.
- No line pair may be ruled `INCOMPATIBLE`, else `ERR_INCOMPATIBLE_TANK_MIX`; and if any pair is ruled `CONDITIONAL`, the payload must set `uses_adjuvant` true, else `ERR_ADJUVANT_REQUIRED`.
- The window must sit inside the prescription's validity: `scheduled_start` on or after `valid_from` and `scheduled_end` on or before `valid_to`, else `ERR_OUTSIDE_APPLICATION_WINDOW`; a range whose start is not strictly before its end is malformed, `ERR_VALIDATION`.
- The field must be free: no other `SCHEDULED` or `IN_PROGRESS` work order on the same field may overlap the new window under a half-open interval test — an existing job's start strictly before the new job's end, and the new job's start strictly before the existing job's end. Adjacency is explicitly allowed on the field: one job ending exactly when another begins does not conflict. A violation is `ERR_FIELD_TIME_CONFLICT`.
- The applicator must be free with travel slack: the same overlap test runs against the applicator's other `SCHEDULED` or `IN_PROGRESS` work, except both intervals are padded by a 30-minute travel buffer — the existing window extends from thirty minutes before its start to thirty minutes after its end. With padding, back-to-back jobs for the same applicator do conflict. A violation is `ERR_APPLICATOR_TIME_CONFLICT`.
- The sprayer must be `AVAILABLE` with a `calibration_valid_until` that is non-null and on or after `scheduled_end`, else `ERR_CALIBRATION_OVERDUE`.
- Finally, the fiscal gate of §2.10: the customer's `outstanding_cents` plus this job's `estimated_total_cents` must not exceed `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`.

When the gauntlet passes, the schedule writes `applicator_id`, `equipment_id`, `scheduled_start`, `scheduled_end`, and `uses_adjuvant` onto the order, computes `estimated_total_cents` as the provisional invoice amount described next, and increments the WorkOrder's `version`.

The provisional amount mirrors the invoice formula of §3.9 run over prescribed rates: a service fee of `acres_to_treat` times the customer's `rate_per_acre_cents`, rounded half-up to whole cents; plus one line per prescribed product of `acres_to_treat` times the line's `rate_per_acre` times the product's `unit_cost_cents` times one plus `markup_pct` over a hundred, each line rounded half-up to whole cents before any summation; the total is the fee plus the sum of the rounded lines.

Plans change, and a `SCHEDULED` order may be amended repeatedly. A reschedule by a `Dispatcher` carries the new `scheduled_start` and `scheduled_end`, optionally a replacement `applicator_id`, `equipment_id`, or `uses_adjuvant`, and — mandatorily — `expected_work_order_version` matching the order's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412) per §2.7. The window and overlap gates re-run for the new window (`ERR_OUTSIDE_APPLICATION_WINDOW`, `ERR_FIELD_TIME_CONFLICT`, `ERR_APPLICATOR_TIME_CONFLICT`); if a new `applicator_id` is present, the applicator existence, active-status, license-expiry, and category gates re-run; if a new `equipment_id` is present, the calibration gate re-runs. A successful reschedule applies the new window and any reassignment and increments the WorkOrder's `version`.

Cancellation is available from `DRAFT` or `SCHEDULED` to the terminal `CANCELLED` state, by the owning `Grower` or a `Dispatcher`, incrementing `version`. And the schedule is not sticky against discipline: the moment the assigned applicator becomes `SUSPENDED` or `REVOKED`, or the assigned sprayer becomes `CALIBRATION_DUE`, each affected `SCHEDULED` order automatically reverts to `DRAFT` — `applicator_id`, `equipment_id`, `scheduled_start`, and `scheduled_end` cleared, `uses_adjuvant` reset to false, `estimated_total_cents` nulled, and `version` incremented.

### 3.5. Execution Under the Sky: Start, Weather Holds, and Completion

Only the assigned applicator may put a job in motion. Starting a `SCHEDULED` work order requires the caller's `X-User-ID` to equal the order's `applicator_id` (else `ERR_FORBIDDEN`), and then clears five gates. The current logical time must be no later than `scheduled_end`, else `ERR_OUTSIDE_APPLICATION_WINDOW`. The field's re-entry lockout must have expired: `rei_until` is either null or the current time is on or after it — the boundary is half-open, so arriving exactly at `rei_until` is permitted — else `ERR_REI_ACTIVE`. The freshest weather observation must be fresh: the WeatherObservation with the greatest `observed_at` (ties broken by the latest `created_at`) must have been taken no more than 60 minutes before now, else `ERR_OBSERVATION_STALE`. That observation must satisfy the mix envelope (below), else `ERR_WEATHER_WINDOW_VIOLATION`. And the applicator must still be `ACTIVE` with `license_expires_on` on or after now, else `ERR_APPLICATOR_NOT_ACTIVE` or `ERR_LICENSE_EXPIRED`. A successful start stamps `started_at` with the logical clock, moves the order to `IN_PROGRESS`, and increments its `version`.

The mix envelope is the intersection of every product's label limits across the prescription's lines. The effective maximum wind is the smallest `max_wind_mph` among the line products; the effective temperature band runs from the largest `min_temp_f` to the smallest `max_temp_f`. The envelope passes when the observation is fresh, its `wind_mph` is at most the effective maximum (a reading exactly equal to the limit passes), its `temp_f` sits inside the band inclusively on both ends, and `inversion_present` is false. The same envelope is evaluated at start, at resume, and — continuously — against every newly posted weather observation.

Weather reporting is shared: an `Applicator` or `Dispatcher` posts an observation with `observed_at`, `wind_mph`, `temp_f`, and `inversion_present`, and the server stamps `recorded_by_user_id` from the caller. The feed lists newest `observed_at` first. Posting an observation is never inert: any `IN_PROGRESS` work order whose mix envelope the new reading violates is automatically moved to `WEATHER_HOLD`, with its `version` incremented. The hold retains the assignment — the same applicator resumes once the sky cooperates.

Resuming a held order again requires the caller to be the assigned applicator (else `ERR_FORBIDDEN`), a fresh observation no older than 60 minutes (else `ERR_OBSERVATION_STALE`), and a passing envelope (else `ERR_WEATHER_WINDOW_VIOLATION`); success returns the order to `IN_PROGRESS` and increments its `version`.

Completion is the applicator's sworn statement. The assigned applicator finishes the job by submitting `lines` — an array of `{ product_id, actual_rate_per_acre }` that must cover exactly the prescription's product set, each product exactly once, every `actual_rate_per_acre` positive; anything else is `ERR_VALIDATION`. Completion then fans out into six effects. The order's `completed_at` is stamped from the logical clock and its status becomes `COMPLETED`. Exactly one ApplicationRecord is created for the work order, born `SUBMITTED`, snapshotting the submitted `lines`, the `applicator_id`, and the `started_at` / `completed_at` pair. The field's `rei_until` advances to the later of its existing value and `completed_at` plus the largest `rei_hours` among the applied products — the lockout never moves earlier — and the Field's `version` increments. Rinsate is accounted: the total spray mix is `acres_to_treat` times the prescription's `carrier_gpa`; the load count is that total divided by the sprayer's `tank_capacity_gal`, rounded up to a whole number; `rinsate_generated_gal` is the load count times `tank_capacity_gal` times two percent — two hundredths of a tank per load — rounded half-up to one decimal place; and `rinsate_balance_gal` opens equal to `rinsate_generated_gal`. A DRAFT Invoice is created for the work order with `provisional_amount_cents` equal to the provisional invoice amount from §3.4 (recomputed at completion from prescribed rates). And the WorkOrder's `version` increments.

### 3.6. Certifying the Paper Trail

The ApplicationRecord is the compliance copy of the job — exactly one per work order, discovered through the `work_order_id` filter on the record list. It lives in three states: born `SUBMITTED`, it may be `CERTIFIED` (terminal), sent back to `RETURNED`, and a returned record may be resubmitted to `SUBMITTED`.

Certification is a second pair of eyes, and the law insists they be different eyes. A `ComplianceOfficer` or an `Applicator` may certify a `SUBMITTED` record, but the certifier's `X-User-ID` must differ from the record's `applicator_id`; certifying one's own work is rejected with `ERR_SEGREGATION_OF_DUTIES`. (An applicator certifying a colleague's record is legitimate and common on small crews.) On certification the server sets `certified_by_user_id` to the certifier's `X-User-ID`, computes the work order invoice's `final_amount_cents` as the final variant of the invoice formula — the same per-line-then-summed, half-up-to-whole-cents structure as the provisional, but run over the record's `actual_rate_per_acre` figures instead of the prescribed rates, so the final diverges from the provisional whenever actuals differed — and increments both the Invoice's `version` and the ApplicationRecord's `version`.

When the paper trail doesn't hold up, a `ComplianceOfficer` returns the record with a `returned_note` explaining the deficiency; an empty or missing note is `ERR_VALIDATION`. The move to `RETURNED` increments the record's `version`. The performing applicator — and only that applicator, matched by `X-User-ID` against the record's `applicator_id` else `ERR_FORBIDDEN` — may then resubmit with corrected `lines` that again cover exactly the prescription's product set (else `ERR_VALIDATION`). Resubmission replaces the lines wholesale, clears `returned_note`, restores `SUBMITTED`, and increments `version`.

### 3.7. Rinsate Accounting and Closing the Job

Sprayer rinse water is regulated waste, and the co-op accounts for every drop generated at completion. The assigned applicator disposes of rinsate by recording a RinsateRecord against the `COMPLETED` work order — posting against an order in any other state is `ERR_INVALID_STATE`. Each record names the `work_order_id`, a `kind` of `FIELD_DISPOSAL` or `CONTAINMENT_DISPOSAL`, and a `volume_gal` that must be positive (else `ERR_VALIDATION`) and no greater than the order's current `rinsate_balance_gal` (else `ERR_RINSATE_OVER_DISPOSAL`). A `FIELD_DISPOSAL` must name a `disposal_field_id`, and it must equal the work order's own `field_id` — rinsate may be land-applied only back onto the field it came from, and any other destination is `ERR_DISPOSAL_FIELD_MISMATCH`. A `CONTAINMENT_DISPOSAL` instead requires a `manifest_no`, the containment manifest number for the hauler. The server stamps `recorded_at` from the logical clock, decrements the work order's `rinsate_balance_gal` by `volume_gal`, and increments the WorkOrder's `version`. Rinsate records are evidence and carry no `updated_at` or `version`; the running balance on the work order is the single source of truth.

Closing is the dispatcher's final checklist, moving a `COMPLETED` order to the terminal `CLOSED` state. Three conditions must all hold: the ApplicationRecord for the work order is `CERTIFIED` (else `ERR_RECORD_NOT_CERTIFIED`), the `rinsate_balance_gal` has been disposed down to exactly zero (else `ERR_RINSATE_BALANCE_OPEN`), and the work order's invoice is settled — `PAID` or `VOIDED` (else `ERR_INVOICE_UNSETTLED`). A successful close increments the WorkOrder's `version`.

### 3.8. Drift Complaints and the Disciplinary Cascade

When spray lands where it shouldn't, the neighbors call the co-op. A `Grower` files a DriftComplaint against a `COMPLETED` work order — filing against an order in any other state is `ERR_INVALID_STATE` — supplying the `work_order_id`, a free-text `description`, and a `severity` of `MINOR` or `MAJOR`. Filing must happen within 30 days of the work order's completion; a complaint arriving later is rejected with `ERR_COMPLAINT_WINDOW_CLOSED`. Only one open complaint may exist per work order: if a complaint for the same order is already `FILED` or `INVESTIGATING`, the new filing is rejected with `ERR_DUPLICATE_OPEN_COMPLAINT`. The server sets `complainant_customer_id` from the caller's `X-User-ID` — the filer may be a neighbor of the treated field, not necessarily the job's customer — and denormalizes the work order's `applicator_id` onto the complaint so later schedule changes cannot rewrite history. New complaints are born `FILED`.

A `ComplianceOfficer` opens the investigation, moving `FILED` to `INVESTIGATING` and incrementing the complaint's `version`. Investigation alone does not suspend anyone — but while any complaint on a work order sits in `FILED` or `INVESTIGATING`, two things freeze: the work order's invoice cannot be issued (`ERR_COMPLAINT_HOLD`), and the named applicator cannot be reinstated from suspension (`ERR_INVESTIGATION_PENDING`).

Substantiation is where the cascade fires. Moving `INVESTIGATING` to the terminal `SUBSTANTIATED` records the investigator's `findings_note` and then detonates three hops. Hop one lands penalty weight on the applicator: two points for a `MINOR` complaint, five for a `MAJOR`. The weight adds to `penalty_points_lifetime`, the sum over all substantiated complaints with no time window and no multiplier. The same substantiation recomputes `rolling_score_365`: the sum of weights over complaints substantiated within the trailing 365 days (the substantiation timestamp is the `updated_at` of the complaint's transition into `SUBSTANTIATED`), doubled whenever at least two substantiations fall within the trailing 90 days. Because the two scores apply different windows, the same complaint set can legitimately yield different lifetime and rolling figures. Hop two moves the license: an `ACTIVE` applicator becomes `SUSPENDED` when the recomputed rolling score is below ten points, while a `SUSPENDED` applicator becomes `REVOKED` — terminal — when the recomputed rolling score reaches at least ten; exactly ten revokes. Either transition increments the Applicator's `version`. Hop three protects future work: every `SCHEDULED` work order assigned to that applicator reverts to `DRAFT` with its assignment cleared, per §2.8. Separately, the complained work order's own invoice is voided in the same breath: a `DRAFT` or `ISSUED` invoice moves to `VOIDED`, and if it had been issued, the customer's `outstanding_cents` is credited by the invoice's `final_amount_cents` with the Customer's `version` incrementing. The complaint's own `version` increments as well.

Dismissal is the quiet ending: `INVESTIGATING` to the terminal `DISMISSED`, with `findings_note` recorded, the complaint's `version` incremented, and no applicator change at all — the investigation never suspended them, and the release lifts the invoice hold.

### 3.9. Invoicing and Settlement

Every completed job carries exactly one Invoice, created `DRAFT` at completion with `provisional_amount_cents` set from prescribed rates and `final_amount_cents` null until the application record is certified. Invoices can be listed and filtered by `work_order_id` or `status`.

Issuing is the billing clerk's commitment, performed by a `CoopAdmin`. Three gates guard the move from `DRAFT` to `ISSUED`: the work order's application record must be `CERTIFIED` so that `final_amount_cents` exists (else `ERR_RECORD_NOT_CERTIFIED`); no complaint on the work order may be `FILED` or `INVESTIGATING` (else `ERR_COMPLAINT_HOLD`); and the customer's `outstanding_cents` plus the invoice's `final_amount_cents` must stay within `credit_limit_cents` (else `ERR_CREDIT_LIMIT_EXCEEDED`). A successful issue debits the customer's `outstanding_cents` by `final_amount_cents`, incrementing the Customer's `version`, and increments the Invoice's `version`.

Payment settles an `ISSUED` invoice into the terminal `PAID` state. Only the invoice's own grower may pay: the caller's `X-User-ID` must equal the `customer_id` of the work order behind the invoice, else `ERR_FORBIDDEN`. Payment credits `outstanding_cents` by `final_amount_cents` (Customer `version` incrementing) and increments the Invoice's `version`.

Voiding unwinds an invoice, either at a `CoopAdmin`'s hand or automatically from the substantiation cascade of §3.8. A `DRAFT` invoice moves to the terminal `VOIDED` state with no balance effect at all — it never debited anything. An `ISSUED` invoice moving to `VOIDED` credits the customer's `outstanding_cents` by `final_amount_cents`, incrementing the Customer's `version`. Either way, the Invoice's `version` increments.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`, as do all reads. The table below is a navigational summary only — request payloads, response bodies, preconditions, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock (test-driving capability) | CoopAdmin |
| POST | `/api/customers` | Create a grower customer account | CoopAdmin |
| GET | `/api/customers/{id}` | Get a customer (Grower reads own id only) | CoopAdmin, Dispatcher, ComplianceOfficer, Grower |
| GET | `/api/customers` | List customer accounts with pagination | CoopAdmin, Dispatcher, ComplianceOfficer |
| POST | `/api/fields` | Create a field (Grower only for own customer_id) | Grower, CoopAdmin |
| GET | `/api/fields/{id}` | Get a field | Grower, Agronomist, Dispatcher, Applicator, ComplianceOfficer, CoopAdmin |
| GET | `/api/fields` | List fields, optionally filtered by customer | Grower, Agronomist, Dispatcher, Applicator, ComplianceOfficer, CoopAdmin |
| POST | `/api/products` | Create a catalog product | CoopAdmin |
| GET | `/api/products/{id}` | Get a product | Grower, Agronomist, Dispatcher, Applicator, ComplianceOfficer, CoopAdmin |
| POST | `/api/compatibility-rules` | Declare an unordered product-pair verdict | CoopAdmin |
| GET | `/api/compatibility-rules/{id}` | Get a compatibility rule | Agronomist, Dispatcher, CoopAdmin |
| GET | `/api/compatibility-rules` | List compatibility rules, either side filterable | Agronomist, Dispatcher, CoopAdmin |
| POST | `/api/prescriptions` | Create a DRAFT prescription | Agronomist |
| GET | `/api/prescriptions/{id}` | Get a prescription | Agronomist, Dispatcher, Grower, CoopAdmin, ComplianceOfficer |
| GET | `/api/prescriptions` | List prescriptions with filters | Agronomist, Dispatcher, Grower, CoopAdmin, ComplianceOfficer |
| POST | `/api/prescriptions/{id}/approve` | Approve a DRAFT prescription (OCC on the field's version) | Agronomist |
| POST | `/api/applicators` | Create an applicator | CoopAdmin |
| GET | `/api/applicators/{id}` | Get an applicator | Dispatcher, ComplianceOfficer, CoopAdmin, Applicator |
| POST | `/api/applicators/{id}/reinstate` | Reinstate a SUSPENDED applicator | ComplianceOfficer |
| POST | `/api/equipment` | Create a sprayer unit | CoopAdmin |
| GET | `/api/equipment/{id}` | Get equipment | Dispatcher, Applicator, CoopAdmin, ComplianceOfficer |
| POST | `/api/calibration-records` | Post a calibration measurement; verdict computed | Applicator, CoopAdmin |
| GET | `/api/calibration-records/{id}` | Get a calibration record | Dispatcher, Applicator, CoopAdmin, ComplianceOfficer |
| GET | `/api/calibration-records` | List calibration records with filters | Dispatcher, Applicator, CoopAdmin, ComplianceOfficer |
| POST | `/api/weather-observations` | Post a weather observation (may hold in-progress jobs) | Applicator, Dispatcher |
| GET | `/api/weather-observations` | List weather observations, newest observed first | Applicator, Dispatcher, CoopAdmin, ComplianceOfficer |
| POST | `/api/work-orders` | Create a DRAFT work order (Grower only for own customer_id) | Grower, Dispatcher |
| GET | `/api/work-orders/{id}` | Get a work order | Grower, Dispatcher, Applicator, ComplianceOfficer, CoopAdmin |
| GET | `/api/work-orders` | List work orders with filters | Grower, Dispatcher, Applicator, ComplianceOfficer, CoopAdmin |
| POST | `/api/work-orders/{id}/schedule` | Assign applicator, equipment, and window; runs the full gate chain | Dispatcher |
| POST | `/api/work-orders/{id}/reschedule` | Amend the window and/or assignment of a SCHEDULED order (OCC) | Dispatcher |
| POST | `/api/work-orders/{id}/start` | Assigned applicator starts the job | Applicator |
| POST | `/api/work-orders/{id}/resume` | Resume from WEATHER_HOLD after a passing fresh observation | Applicator |
| POST | `/api/work-orders/{id}/complete` | Complete the job with actual product rates | Applicator |
| POST | `/api/work-orders/{id}/cancel` | Cancel a DRAFT or SCHEDULED work order | Grower, Dispatcher |
| POST | `/api/work-orders/{id}/close` | Close a COMPLETED work order | Dispatcher |
| GET | `/api/application-records/{id}` | Get an application record | Dispatcher, Applicator, ComplianceOfficer, CoopAdmin |
| GET | `/api/application-records` | List application records with filters | Dispatcher, Applicator, ComplianceOfficer, CoopAdmin |
| POST | `/api/application-records/{id}/certify` | Certify a SUBMITTED record (segregation of duties enforced) | ComplianceOfficer, Applicator |
| POST | `/api/application-records/{id}/return` | Return a SUBMITTED record for correction | ComplianceOfficer |
| POST | `/api/application-records/{id}/resubmit` | Resubmit a RETURNED record with corrected lines | Applicator |
| POST | `/api/rinsate-records` | Record a rinsate disposal against a COMPLETED work order | Applicator |
| GET | `/api/rinsate-records/{id}` | Get a rinsate record | Dispatcher, Applicator, ComplianceOfficer, CoopAdmin |
| GET | `/api/rinsate-records` | List rinsate records with filters | Dispatcher, Applicator, ComplianceOfficer, CoopAdmin |
| POST | `/api/drift-complaints` | File a drift complaint against a COMPLETED work order | Grower |
| GET | `/api/drift-complaints/{id}` | Get a drift complaint | Grower, ComplianceOfficer, CoopAdmin |
| GET | `/api/drift-complaints` | List drift complaints with filters | Grower, ComplianceOfficer, CoopAdmin |
| POST | `/api/drift-complaints/{id}/open-investigation` | Move a FILED complaint to INVESTIGATING | ComplianceOfficer |
| POST | `/api/drift-complaints/{id}/substantiate` | Substantiate an INVESTIGATING complaint (disciplinary cascade) | ComplianceOfficer |
| POST | `/api/drift-complaints/{id}/dismiss` | Dismiss an INVESTIGATING complaint | ComplianceOfficer |
| GET | `/api/invoices/{id}` | Get an invoice | Grower, Dispatcher, CoopAdmin, ComplianceOfficer |
| GET | `/api/invoices` | List invoices with filters | Grower, Dispatcher, CoopAdmin, ComplianceOfficer |
| POST | `/api/invoices/{id}/issue` | Issue a DRAFT invoice after certification | CoopAdmin |
| POST | `/api/invoices/{id}/pay` | Pay an own ISSUED invoice | Grower |
| POST | `/api/invoices/{id}/void` | Void a DRAFT or ISSUED invoice | CoopAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is the identifier-to-status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PRESCRIPTION_NOT_APPROVED` | 409 Conflict |
| `ERR_APPLICATOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_RECORD_NOT_CERTIFIED` | 409 Conflict |
| `ERR_INVESTIGATION_PENDING` | 409 Conflict |
| `ERR_REI_ACTIVE` | 409 Conflict |
| `ERR_WEATHER_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_OBSERVATION_STALE` | 409 Conflict |
| `ERR_LICENSE_EXPIRED` | 409 Conflict |
| `ERR_LICENSE_CATEGORY_MISSING` | 409 Conflict |
| `ERR_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_INCOMPATIBLE_TANK_MIX` | 409 Conflict |
| `ERR_ADJUVANT_REQUIRED` | 409 Conflict |
| `ERR_OUTSIDE_APPLICATION_WINDOW` | 409 Conflict |
| `ERR_FIELD_TIME_CONFLICT` | 409 Conflict |
| `ERR_APPLICATOR_TIME_CONFLICT` | 409 Conflict |
| `ERR_CALIBRATION_OVERDUE` | 409 Conflict |
| `ERR_COMPLAINT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ACREAGE_EXCEEDED` | 409 Conflict |
| `ERR_RINSATE_BALANCE_OPEN` | 409 Conflict |
| `ERR_RINSATE_OVER_DISPOSAL` | 409 Conflict |
| `ERR_DISPOSAL_FIELD_MISMATCH` | 409 Conflict |
| `ERR_COMPLAINT_HOLD` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_COMPLAINT` | 409 Conflict |
| `ERR_INVOICE_UNSETTLED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
