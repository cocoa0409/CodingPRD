# UST Compliance API — Product Requirements Document

## 1. Introduction

Underground storage tank owners operate under continuous regulatory exposure. Every tank, product line, leak detector, and spill containment device at a facility carries recurring test obligations; every month of missing release-detection monitoring is a citable gap; every suspected release starts a twenty-four-hour notification clock; and every cleanup dollar recovered from a state trust fund must survive deductible, coinsurance, and annual-cap accounting. The testing contractors who service these facilities, meanwhile, must dispatch properly endorsed technicians, produce defensible test records, and keep field work strictly segregated from certification.

This document specifies the UST Compliance API, the system of record for that compliance ecosystem. It governs facility and tank inventory with forward-looking test scheduling; dispatch, execution, review, and certification of tank and line tightness tests, leak-detector function checks, cathodic protection surveys, and spill/overfill inspections; the deficiency correction and re-test loop; monthly release-detection records and their bundling into regulatory submissions; Class A/B/C operator designation and training credentialing; suspected-release reporting; and state fund claims. Five acting roles collaborate under strict segregation of duties, an optimistic-concurrency regime protects contested records, and a live compliance posture score quantifies each facility's regulatory standing for owners, contractors, and the state.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the caller's role is not among the roles an endpoint authorizes, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes six roles: `FacilityOwner`, `ContractorAdmin`, `Technician`, `ComplianceReviewer`, `StateRegulator`, and `Any` — the last being a read-only capacity shared by every authenticated caller across all list and detail endpoints.

Identity binding differs by role, and the distinction drives every ownership check in the system:

- When `X-User-Role` is `FacilityOwner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `owner_account_id` on the Facility at registration time, and owner-gated operations compare the caller's `X-User-ID` against that stored field; it is never compared to any entity's `id`.
- When `X-User-Role` is `ContractorAdmin`, `X-User-ID` is likewise an opaque back-office identifier. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting Technician resource. Ownership checks on a service order compare the order's technician fields to `X-User-ID`, and issuing a training certificate stamps `instructor_technician_id` from the same value.
- When `X-User-Role` is `ComplianceReviewer`, `X-User-ID` is again the `id` of a Technician resource — reviewers are technicians acting in a certifying capacity. The server records it as `certified_by_technician_id` when an order is certified, and compares it against `performed_by_technician_id` to enforce segregation of duties.
- When `X-User-Role` is `StateRegulator`, `X-User-ID` is an opaque agency identifier not tied to any persisted entity. The server may record it alongside review actions (for example, the `state_reviewer_note` written on a rejected RegulatorySubmission) but does not compare it to any entity's `id`.

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

Requests that never reach an endpoint still produce this envelope: a path matching no endpoint is rejected with `ERR_NOT_FOUND` (HTTP 404), a matched path called with an unsupported method returns the same `ERR_NOT_FOUND` body with HTTP 405, and an unexpected server failure returns `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, and a supplied value outside the range 1 to 100 is clamped to the nearest bound rather than rejected. The `offset` parameter specifies how many items to skip; it defaults to 0, and a negative value is clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties — possible because all timestamps derive from the settable logical clock — broken by creation order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every time-dependent rule in the system — service windows, correction deadlines, certificate expiries, reporting lateness, period boundaries — evaluates against a server-maintained logical clock, never against wall-clock time. Before any client sets it, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `ContractorAdmin` may set the clock through a test-driving capability that accepts a `to_iso8601` timestamp and echoes the new `current_utc`. Once set, the clock remains at the supplied instant until it is set again; it never falls back to wall-clock time on its own.

### 2.5. Common Resource Properties

Most resources in the system carry a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed upon any change to the resource's properties, and equal to `created_at` at creation.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by 1 on every mutation of the resource, including mutations driven by system cascades.

Two resources are deliberately immutable ledgers and deviate from this convention: a ResultRecord and a TrainingRecord each carry only `id` and `created_at`. Both `updated_at` and `version` are absent from them, because neither resource can ever be modified after creation.

### 2.6. Ownership Anchors, Nested Retrieval, and Hierarchical Cascades

Ownership in this system flows through the Facility. Every operation gated to a `FacilityOwner` — tank registration and closure, component registration, deficiency correction, operator designation, monthly record keeping, release reporting, fund claims — requires the caller's `X-User-ID` to equal the parent facility's `owner_account_id`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. The same error protects technician-owned work: starting an order or recording its results requires the caller to be the technician bound to that order.

For any request whose path or payload references multiple resources, the system validates existence in a strict left-to-right order, rejecting with the not-found error of the first missing resource before examining later ones: `ERR_FACILITY_NOT_FOUND`, `ERR_TANK_SYSTEM_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_RESULT_RECORD_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`, `ERR_TRAINING_RECORD_NOT_FOUND`, `ERR_RELEASE_EVENT_NOT_FOUND`, and `ERR_FUND_CLAIM_NOT_FOUND` each name the resource type that failed lookup.

State changes on a parent resource propagate downward to keep the hierarchy coherent. Closing a tank cancels its pending service orders; permanently closing a tank retires its components; closing a facility cancels its pending orders and revokes its operators; confirming a release closes the affected tank temporarily. Each resource touched by such a cascade is itself mutated: its `updated_at` refreshes and its `version` increments by 1, independently of whatever endpoint the client called.

### 2.7. Request Validation Precedence

When several checks guard the same operation, the system evaluates them in a fixed precedence so that the earliest failing check determines the error returned, and no later check can mask an earlier failure. The order is:

1. Authentication context — the `X-User-ID` and `X-User-Role` headers are present and non-empty.
2. Role authorization — the caller's role appears in the endpoint's authorized roles.
3. Existence — path identifiers resolve left-to-right, then the body references that anchor the operation's ownership check (the `facility_id`, or the `tank_system_id` whose facility anchors the check); a resource must be loaded before its owner or state can be examined.
4. Ownership — the caller owns the facility, or is the technician bound to the order. On the technician-bound order actions (starting an order, recording its results), the order's state precondition is evaluated before this technician-binding check.
5. State preconditions and remaining references — the target resource sits in the from-state the transition requires, and the remaining body foreign-key references (`component_id`, `technician_id`, `operator_id`, `release_event_id`, `linked_deficiency_id`, and any bundled identifier lists) resolve; the endpoint narratives in §3 pin the relative order where both apply to one call.
6. Segregation of duties at certification.
7. Technician endorsement and active-status rules for scheduling.
8. Training issuance rules (trainer flag, class match).
9. The facility posture gate on fund claim creation.
10. Uniqueness constraints.
11. Window validity (`window_end` strictly after `window_start`).
12. Technician double-booking.
13. The tank stabilization buffer.
14. The service-window containment gate on starting work.
15. Period rules (monthly-close timing, future periods, tank status for record creation).
16. Training validity at operator activation.
17. Cross-referential alignment (tank-to-facility, component-to-service-type, deficiency links, submission bundles, claim-to-release).
18. Fund fiscal gates (release status, fee currency, fund cap).
19. Optimistic concurrency version matching.

A payload that is malformed in its own right — a required field missing, a malformed value, an unrecognized enum, a bad `YYYY-MM` month format, an empty `expense_lines` array, or a `readings` object that does not match the schema of the order's service type — is rejected with `ERR_INVALID_REQUEST`. Payload schemas are closed: a field the endpoint does not declare is likewise rejected with `ERR_INVALID_REQUEST`. The exceptions are the body-less transition endpoints — facility activation and closure, deficiency order-correction and mark-corrected, operator activation and revocation, submission submit and accept, release confirm, dismiss, begin-cleanup, and close, and claim submit and withdraw — which ignore any supplied body. The service-order action endpoints (start, certify, return-for-correction, cancel) declare no inputs and reject any supplied field.

### 2.8. Optimistic Concurrency Control

Two write operations in the system carry optimistic concurrency protection, and only these two take a version field.

Editing a service order requires the request to carry `expected_service_order_version`, holding the `version` of the order as the client last observed it. If the supplied value does not equal the order's current `version` — typically because another dispatcher edited the order in the meantime — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the order before retrying.

Amending a rejected regulatory submission requires `expected_submission_version` carrying the client's last observed `version` of the submission. If the supplied value does not equal the submission's current `version` — for instance because a `state_reviewer_note` was written after the client last read it — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412); the client must re-read the submission and re-issue the amendment against the fresh version.

No other endpoint accepts a version field.

### 2.9. The Facility Compliance Posture Score

Every facility carries a `posture_score`, an integer from 0 to 100 that begins at 100 at registration, and a derived `compliance_posture` label. The score is recomputed from the facility's live obligations whenever a deficiency is opened, verified, escalated, or de-escalated; whenever a release event is created, confirmed, dismissed, or closed; whenever an operator lapses, is activated, or is revoked through the revoke endpoint (operator revocation cascading from facility closure does not itself trigger a recompute); and once at the end of every monthly close.

The computation starts at 100 points. Each deficiency of the facility in `OPEN`, `CORRECTION_ORDERED`, `CORRECTED`, `RE_TEST_SCHEDULED`, or `ESCALATED` status subtracts its severity weight — 25 points for `CRITICAL`, 15 for `MAJOR`, 5 for `MINOR` — and an `ESCALATED` deficiency subtracts a further 5 points on top of its severity weight. Each release event of the facility in `SUSPECTED`, `CONFIRMED`, or `CLEANUP_IN_PROGRESS` status subtracts 10 points. Each operator of the facility in `LAPSED` status subtracts 5 points. The result is clamped so it never falls below 0 and never exceeds 100. The label follows the score: `COMPLIANT` when the score is at least 85, `DEFICIENT` when it is at least 60 but below 85, and `NON_COMPLIANT` when it falls below 60. Deficiencies that have reached `VERIFIED_CLOSED` and releases that are `DISMISSED` or `CLOSED` no longer count against the score.

A facility read returns the posture fields as of the latest recompute. The posture gate has teeth: a facility in `NON_COMPLIANT` posture cannot open a state fund claim.

### 2.10. Cents, Millivolts, and Rounding Conventions

All monetary values in the system — quote totals, claim amounts, deductibles, the fund cap — are represented as integer cents. Service quotes round each line's amount half-up to whole cents before summing, and the coinsurance product on fund claims applies a single round-half-up to whole cents; no other rounding occurs anywhere in monetary math. Test measurements keep their own precision and are never rounded: a leak-rate reading is compared exactly against a threshold expressed at 3 decimal places, an overfill activation percentage exactly against a threshold expressed at 1 decimal place, and cathodic protection voltages as integer millivolts. Timestamp comparisons are strict exactly where the governing rule says so — a deadline exceeded, an expiry reached — and inclusive where the rule says so, and the prose below calls out each bound explicitly.

### 2.11. Segregation of Duties Between Field and Office

The person who performs a test may never be the person who certifies it. Every service order records the technician who started it as `performed_by_technician_id`, and certification records the reviewer as `certified_by_technician_id`. Certification by the same technician who performed the work is rejected with `ERR_SELF_CERTIFICATION` (HTTP 403). This segregation anchors the order's review workflow and is enforced after ownership and state checks, before any business rules run.

## 3. Business Logic & Workflows

### 3.1. Facility Registration and Tank Inventory

A `FacilityOwner` begins by registering a facility with its `facility_name`, two-letter `state_code`, and `annual_fee_paid_through` — the timestamp through which the state fund annual fee is paid. The registration may also declare a `fund_program_election` of `PER_OCCURRENCE` or `AGGREGATE`; when omitted, the election defaults to `PER_OCCURRENCE`. The new facility is stamped with the caller's identity as `owner_account_id`, enters in `REGISTERED` status, and is initialized with a `posture_score` of 100 and `compliance_posture` of `COMPLIANT`, a `fund_cap_remaining_cents` of 100000000 cents (one million dollars) for the fund year, and a `fund_year_deductible_remaining_cents` pool of 2000000 cents (twenty thousand dollars). The facility directory can be listed with filters on `state_code`, `owner_account_id`, and `status`.

Against a facility, the owner registers tank systems. A tank record captures `facility_id`, an operator-facing `tank_tag` that must be unique within the facility (a duplicate is rejected with `ERR_DUPLICATE_TANK_TAG`), the stored `substance` (`GASOLINE`, `DIESEL`, `KEROSENE`, or `USED_OIL`), the nominal `capacity_gallons`, the `installed_on` date that anchors first test due dates, the `tank_construction` (`STEEL`, `FRP`, or `COMPOSITE`), the `piping_type` (`PRESSURIZED`, `SUCTION`, or `GRAVITY`), and the `release_detection_mode` (`INTERSTITIAL_MONITORING`, `ATG_INVENTORY`, or `MANUAL_GAUGING`). Manual gauging is only lawful on small tanks: choosing `MANUAL_GAUGING` with a `capacity_gallons` above 2000 is rejected with `ERR_MODE_NOT_ALLOWED_FOR_CAPACITY`. A new tank enters in `REGISTERED` status. The tank inventory lists with `facility_id` and `status` filters.

Components hang beneath tanks. Registering a component requires `tank_system_id`, a `component_type` of `SPILL_BUCKET`, `OVERFILL_DEVICE`, `LINE_LEAK_DETECTOR`, or `CATHODIC_PROTECTION`, plus `install_date` and `serial_no`. Components are born `IN_SERVICE` and can be listed by `tank_system_id`, `component_type`, and `status`.

Activation proceeds bottom-up. A tank moves from `REGISTERED` to `IN_SERVICE` when its owner places it in service, which requires the parent facility to be `ACTIVE`; otherwise the request fails with `ERR_FACILITY_NOT_ACTIVE`, and placing a tank that is not `REGISTERED` in service is rejected with `ERR_TANK_NOT_IN_SERVICE`. The facility itself moves from `REGISTERED` to `ACTIVE` only once at least one tank system exists for it; activation from any other status is rejected with `ERR_FACILITY_NOT_ACTIVE`, and activation with no tank registered is rejected with `ERR_NO_TANK_REGISTERED`.

From the inventory the system projects each tank's future test obligations through a test-schedule capability that returns the `tank_system_id` and a list of `items`, one per applicable test type, each carrying a `test_type` and a `due_at`. Applicability and interval follow the tank's equipment profile: a `TANK_TIGHTNESS` test is required unless the tank's `release_detection_mode` is `INTERSTITIAL_MONITORING`, recurring every 12 months for `ATG_INVENTORY` tanks and every 60 months for `MANUAL_GAUGING` tanks; a `LINE_TIGHTNESS` test is required only when the `piping_type` is `PRESSURIZED`, every 12 months; an `LLD_FUNCTION` check is required only when a `LINE_LEAK_DETECTOR` component exists on the tank, every 12 months; a `CP_SURVEY` is required only when a `CATHODIC_PROTECTION` component exists, every 36 months; and a `SPILL_OVERFILL_INSPECTION` is required only when a `SPILL_BUCKET` or `OVERFILL_DEVICE` component exists, every 36 months. Each `due_at` is computed by taking the tank's latest `CERTIFIED` service order of that test type — latest meaning the last when such orders are ordered by `window_end` ascending with ties broken by creation order (the sequence in which the orders were created) — and adding the interval to that order's `window_end`; when no certified order of that type exists, the interval is added to the tank's `installed_on`. Month arithmetic is performed at whole-month granularity anchored to the source timestamp's day. The projection's items are sorted by `due_at` ascending, with ties broken by the `test_type` name ascending.

### 3.2. Closures, Cascades, and Returning Tanks to Service

Tanks leave service along two paths. A temporary closure — initiated by the owner with a `closure_type` of `TEMPORARY` — moves an `IN_SERVICE` tank to `TEMPORARILY_CLOSED`; from any other status the request is rejected with `ERR_TANK_NOT_IN_SERVICE`. The same transition fires without any owner action when a `CRITICAL` deficiency opens against the tank or when a linked release event is confirmed. Every form of temporary closure cancels the tank's service orders still in `REQUESTED` or `SCHEDULED`, and each cancelled order that was acting as a re-test moves its linked `RE_TEST_SCHEDULED` deficiency back to `CORRECTED`.

A permanent closure — `closure_type` of `PERMANENT` — moves a tank from either `IN_SERVICE` or `TEMPORARILY_CLOSED` to `PERMANENTLY_CLOSED`, a terminal state; any other from-state is rejected with `ERR_TANK_NOT_IN_SERVICE`. On top of the same order-cancellation cascade, every component of the tank in `IN_SERVICE` or `DEFICIENT` is retired to `OUT_OF_SERVICE`. Components also track deficiency state on their own: when a deficiency referencing a component opens, that component moves from `IN_SERVICE` to `DEFICIENT`, and when that deficiency is verified closed, the component returns from `DEFICIENT` to `IN_SERVICE`.

Returning a temporarily closed tank to service is an owner action — the tank must sit in `TEMPORARILY_CLOSED`, failing which the request is rejected with `ERR_TANK_NOT_IN_SERVICE` — with two hard gates. If any deficiency on the tank has severity `CRITICAL` and status `OPEN`, `CORRECTION_ORDERED`, or `ESCALATED`, the return is rejected with `ERR_CRITICAL_DEFICIENCY_OPEN`; a `CRITICAL` deficiency in `CORRECTED` or `RE_TEST_SCHEDULED` does not block, because the correction is applied and only verification remains. If any release event on the tank sits in `SUSPECTED`, `CONFIRMED`, or `CLEANUP_IN_PROGRESS`, the return is rejected with `ERR_OPEN_RELEASE_ON_TANK`. A clean return moves the tank `TEMPORARILY_CLOSED` → `IN_SERVICE`.

Closing a facility is the terminal act of its lifecycle. The owner may close an `ACTIVE` facility only when every one of its tanks is `PERMANENTLY_CLOSED`; closing a facility that is not `ACTIVE` is rejected with `ERR_FACILITY_NOT_ACTIVE`, and an `ACTIVE` facility with any tank not `PERMANENTLY_CLOSED` fails with `ERR_TANKS_NOT_CLOSED`. Closure cascades widely: every facility service order still in `REQUESTED` or `SCHEDULED` is cancelled (with the same re-test deficiency fallback to `CORRECTED`), and every operator of the facility in `DESIGNATED`, `ACTIVE`, or `LAPSED` is revoked. The facility ends in `CLOSED`.

### 3.3. Quoting, Dispatching, and Editing Service Orders

All billable field work runs through service orders, created by a `ContractorAdmin`. The creation payload names the `facility_id`, the `tank_system_id` under test, the `service_type` — one of `TANK_TIGHTNESS`, `LINE_TIGHTNESS`, `LLD_FUNCTION`, `CP_SURVEY`, or `SPILL_OVERFILL_INSPECTION` — and the `line_items` that price the job. Each line item carries a `description`, a `qty` that may be fractional, and an integer `unit_price_cents`. The quote total is computed in a pinned order: for each line, the quantity is multiplied by the unit price and that product is rounded half-up to whole cents; the rounded line amounts are then summed; and a flat mobilization charge of 15000 cents is added to the sum, yielding `quote_total_cents`. Rounding per line first and then summing is mandatory — summing exact products and rounding once at the end produces different cents and is incorrect.

Cross-references are validated at creation. The tank must belong to the named facility, or the request fails with `ERR_TANK_FACILITY_MISMATCH`. Component-level service types demand a `component_id`: a `CP_SURVEY` order must reference a `CATHODIC_PROTECTION` component, an `LLD_FUNCTION` order a `LINE_LEAK_DETECTOR`, and a `SPILL_OVERFILL_INSPECTION` a `SPILL_BUCKET` or `OVERFILL_DEVICE`, and in every case the component must live on the order's tank; tightness orders (`TANK_TIGHTNESS`, `LINE_TIGHTNESS`) must carry no component at all. Any violation — a missing component where one is required, a present component where none is allowed, a component on the wrong tank, or the wrong component type for the service — is rejected with `ERR_COMPONENT_MISMATCH`. An order may also be marked as the re-test for an existing deficiency by supplying `linked_deficiency_id`; that deficiency must belong to the same tank and sit in `OPEN`, `CORRECTION_ORDERED`, or `CORRECTED` status, failing which the create is rejected with `ERR_DEFICIENCY_LINK_INVALID`. A new order enters in `REQUESTED` status with `result_outcome` of `NONE` and with `technician_id`, `window_start`, `window_end`, `performed_by_technician_id`, and `certified_by_technician_id` all null. Dispatchers can sift the order book by `facility_id`, `tank_system_id`, `component_id`, `technician_id`, `linked_deficiency_id`, `performed_by_technician_id`, `certified_by_technician_id`, and `status`.

Scheduling converts a request into an assignment. A `ContractorAdmin` schedules an order by naming the `technician_id` and the half-open service window from `window_start` (inclusive) to `window_end` (exclusive). The checks run in order: the named technician must exist (`ERR_TECHNICIAN_NOT_FOUND`); the order must be `REQUESTED` (`ERR_ORDER_NOT_REQUESTED`); the tank must be `IN_SERVICE` (`ERR_TANK_NOT_IN_SERVICE`); the technician must be `active` and hold the endorsement the service type maps to — `TIGHTNESS_TESTER` for `TANK_TIGHTNESS` and `LINE_TIGHTNESS`, `LLD_TESTER` for `LLD_FUNCTION`, `CP_TESTER` for `CP_SURVEY`, and `INSPECTOR` for `SPILL_OVERFILL_INSPECTION` — with a missing endorsement or an inactive technician rejected as `ERR_ENDORSEMENT_MISSING`; the window must be valid, meaning `window_end` strictly after `window_start` (`ERR_INVALID_WINDOW`); the technician must have no other `SCHEDULED` or `IN_PROGRESS` order whose half-open window intersects the requested one, with mere adjacency — one window's end equal to the other's start — explicitly allowed (`ERR_TECHNICIAN_DOUBLE_BOOKED`); and, for `TANK_TIGHTNESS` orders, the tank must have had no other `TANK_TIGHTNESS` order in `SCHEDULED`, `IN_PROGRESS`, or `CERTIFIED` whose window ends less than 8 hours before the requested `window_start` or starts less than 8 hours after the requested `window_end`, a stabilization buffer in which exactly 8 hours of separation is permitted (`ERR_TANK_STABILIZATION_WINDOW`). Scheduling stamps the technician and window onto the order, and when the order carries a `linked_deficiency_id` whose deficiency is `CORRECTED`, that deficiency advances to `RE_TEST_SCHEDULED` — the re-test is on the calendar.

While an order remains `REQUESTED` or `SCHEDULED`, a dispatcher may edit its line items, window, or technician; editing an order in any other status is rejected with `ERR_ORDER_NOT_EDITABLE`. The edit must carry `expected_service_order_version` as described in §2.8, and a stale version is rejected with `ERR_STALE_VERSION`; the editability check runs before a newly supplied `technician_id` is resolved, and the version comparison runs last — after the editability check and any re-run business checks have passed. When `line_items` are supplied, `quote_total_cents` is recomputed by the same per-line rounding rule. When window or technician change on a `SCHEDULED` order, the endorsement, double-booking, stabilization, and window-validity checks re-run against the merged new values, surfacing `ERR_ENDORSEMENT_MISSING`, `ERR_TECHNICIAN_DOUBLE_BOOKED`, `ERR_TANK_STABILIZATION_WINDOW`, or `ERR_INVALID_WINDOW` as applicable.

Cancellation is available to a `ContractorAdmin` while the order is `REQUESTED` or `SCHEDULED`; any other status yields `ERR_ORDER_NOT_CANCELLABLE`. Cancellation moves the order to its terminal `CANCELLED` state, and when the cancelled order was acting as a re-test, its linked `RE_TEST_SCHEDULED` deficiency falls back to `CORRECTED`. Cancellation also arrives uninvited through the closure and release cascades of §3.2 and §3.8.

### 3.4. Fieldwork Execution and Result Determination

Field work belongs to technicians. A `ContractorAdmin` registers each technician with a `full_name`, an `endorsements` array drawn from `TIGHTNESS_TESTER`, `LLD_TESTER`, `CP_TESTER`, and `INSPECTOR`, and an optional `trainer` flag that defaults to false; new technicians are `active` by default, and an inactive technician cannot be scheduled. The technician directory lists with `endorsement` and `active` filters.

Only the assigned technician may start an order, and only inside its window: starting requires the order to be `SCHEDULED` (`ERR_ORDER_NOT_SCHEDULED`), the caller's `X-User-ID` to equal the order's `technician_id` (`ERR_NOT_RESOURCE_OWNER`), and the logical clock to fall at or after `window_start` and at or before `window_end` (`ERR_OUTSIDE_SERVICE_WINDOW` when outside). Starting moves the order `SCHEDULED` → `IN_PROGRESS` and records the caller as `performed_by_technician_id`.

The performing technician then records the test's `readings`, whose shape is dictated by the service type; a `readings` object that does not conform to the order's type schema is rejected with `ERR_INVALID_REQUEST`. Recording results creates an immutable ResultRecord bound to the order through `service_order_id`, stamped with `recorded_at` from the logical clock, carrying the submitted `readings` and a computed `outcome`, and mirrors that outcome onto the order's `result_outcome` — so `result_outcome` always reflects the latest ResultRecord on the order. The order moves `IN_PROGRESS` → `UNDER_REVIEW`; attempting to record results on an order that is not `IN_PROGRESS` fails with `ERR_ORDER_NOT_IN_PROGRESS`, and only the technician recorded as `performed_by_technician_id` may record.

Outcome determination is mechanical. For `TANK_TIGHTNESS` and `LINE_TIGHTNESS`, the reading is `leak_rate_gph` in gallons per hour, compared exactly — the reading itself is never rounded — against the 3-decimal-place threshold: the test passes when the leak rate is at most 0.100 — a reading of exactly 0.100 passes — and fails otherwise. For `LLD_FUNCTION`, the reading `detects_simulated_leak` must be true to pass. For `SPILL_OVERFILL_INSPECTION`, passing requires all three conditions: `visual_cracks_found` is false, `drain_test_hold_minutes` is at least 5 minutes (exactly 5 passes), and `overfill_activates_pct` — compared exactly, again without rounding the reading, against the 1-decimal-place threshold — is at most 95.0 (exactly 95.0 passes). None of these four test types can yield `INCONCLUSIVE`.

Cathodic protection surveys follow their own rule. The readings comprise `instant_off_mv`, `polarized_mv`, `native_mv`, `valid_contact`, and `criterion`, with voltages in integer millivolts. When `valid_contact` is false, the outcome is `INCONCLUSIVE` and the voltages are ignored. Otherwise the `criterion` selects the pass test: under `INSTANT_OFF`, the survey passes when `instant_off_mv` is at most −850 millivolts — that is, at least 850 millivolts of cathodic polarization, with exactly −850 passing. Under `POLARIZATION_SHIFT`, the formation shift is computed as `native_mv` minus `polarized_mv`, and the survey passes when that shift is at least 100 millivolts, with exactly 100 passing. The two criteria are genuinely different instruments: an identical voltage triple can pass under `POLARIZATION_SHIFT` while failing under `INSTANT_OFF`. Any survey that is neither inconclusive nor passing fails.

Failure is an event, not just a number. When a `TANK_TIGHTNESS` or `LINE_TIGHTNESS` order fails, the system opens a `CRITICAL` deficiency of origin `TEST_FAILURE` with `source_service_order_id` pointing at the failing order and no component, and simultaneously opens a `SUSPECTED` release event with `discovered_at` set to the current clock and `tank_system_id` set to the tested tank. The new `CRITICAL` deficiency then drives the tank into `TEMPORARILY_CLOSED`, which cancels the tank's remaining `REQUESTED` and `SCHEDULED` orders and falls their linked re-test deficiencies back to `CORRECTED`. When a `CP_SURVEY`, `LLD_FUNCTION`, or `SPILL_OVERFILL_INSPECTION` order fails, the system instead opens a `MAJOR` deficiency of origin `TEST_FAILURE` referencing the tested component, and that component moves to `DEFICIENT`. Whenever any deficiency is created, the facility's `posture_score` and `compliance_posture` are recomputed.

One suppression rule keeps the re-test loop from self-destructing: when the failing order carries a `linked_deficiency_id`, a `FAIL` outcome creates no new deficiency and no new release event. The linked deficiency's fate is decided later, at certification.

### 3.5. Certification, Rework, and the Deficiency Correction Loop

Certification is the office's signature on field work. A `ComplianceReviewer` certifies an order in `UNDER_REVIEW` (`ERR_ORDER_NOT_UNDER_REVIEW` otherwise), subject to the segregation rule of §2.11: the reviewer's `X-User-ID` must differ from the order's `performed_by_technician_id`, else `ERR_SELF_CERTIFICATION`. Certification stamps `certified_by_technician_id` with the caller and moves the order to its terminal `CERTIFIED` state. When the certified order was a re-test — its `linked_deficiency_id` pointing at a deficiency in `RE_TEST_SCHEDULED` — the outcome resolves the loop: a `PASS` moves the deficiency to `VERIFIED_CLOSED`, records the certifying order as `verified_by_service_order_id`, restores any referenced component to `IN_SERVICE`, and recomputes the facility posture now that the deficiency has left the open set; a `FAIL` loops the deficiency back to `CORRECTION_ORDERED` with a posture recompute; an `INCONCLUSIVE` outcome leaves the deficiency in `RE_TEST_SCHEDULED` awaiting further action.

Review can instead bounce the work back. Returning an order for correction moves it `UNDER_REVIEW` → `IN_PROGRESS` for rework; the recorded `result_outcome` stays as it was, and all prior ResultRecords remain immutable. A subsequent results recording simply adds a new ResultRecord — the result-record ledger lists oldest first, filterable by `service_order_id` and `outcome`, so a multi-record rework history replays deterministically.

The deficiency itself has its own lifecycle, tracked on a record that carries `facility_id`, `tank_system_id`, an optional `component_id` (set only when the failing order targeted a component), `source_service_order_id` (null for sweep-created rows), `verified_by_service_order_id` (null until verified), an `origin` of `TEST_FAILURE` or `CLOSE_SWEEP`, a `period_month` set only for sweep-created rows, a `severity`, a human-readable `description`, and a `correction_deadline` fixed at creation. Severity follows the failure that opened the deficiency: `CRITICAL` for tank and line tightness failures, `MAJOR` for cathodic protection, leak detector, and spill/overfill failures, and `MINOR` for monthly-record gaps found by the sweep. The deadline is the deficiency's `created_at` plus 7 days for `CRITICAL`, 30 days for `MAJOR`, or 90 days for `MINOR`, and it never moves afterwards. Deficiencies list with filters on `facility_id`, `tank_system_id`, `component_id`, `source_service_order_id`, `verified_by_service_order_id`, `status`, and `severity`.

The owner drives correction. Ordering correction moves a deficiency from `OPEN` — or from `ESCALATED` — to `CORRECTION_ORDERED` (`ERR_DEFICIENCY_NOT_OPEN` from any other status). Once the physical fix is applied, marking corrected moves `CORRECTION_ORDERED` → `CORRECTED` (`ERR_DEFICIENCY_NOT_ORDERED` otherwise). A `CORRECTED` deficiency then waits for its re-test: scheduling a service order that links it moves it to `RE_TEST_SCHEDULED`, certification resolves it as above, and cancellation of the linked order drops it back to `CORRECTED`. `VERIFIED_CLOSED` is terminal.

Time is not on the owner's side. At every monthly close, any deficiency whose correction deadline has passed — the logical clock strictly later than `correction_deadline` — and whose status is `OPEN`, `CORRECTION_ORDERED`, `CORRECTED`, or `RE_TEST_SCHEDULED` escalates to `ESCALATED`, stamping `escalated_at` with the clock and recomputing the facility posture with the escalation surcharge. Escalation does not close any doors: an `ESCALATED` deficiency can still be ordered into correction.

### 3.6. Monthly Records and Regulatory Submissions

Release detection is a monthly discipline. For each tank that is `IN_SERVICE` or `TEMPORARILY_CLOSED` — a record against any other tank status is rejected with `ERR_TANK_NOT_IN_SERVICE` — the owner records a release-detection record for each `period_month` in `YYYY-MM` format, supplying `tank_system_id` and a free-form `readings_summary` object. The period must not be after the logical clock's current month (`ERR_FUTURE_PERIOD`), and only one record may exist per tank and period (`ERR_DUPLICATE_RECORD`). At creation the record's `method` is copied from the tank's `release_detection_mode`, and the record enters in `RECORDED` status. Records list by `tank_system_id`, `period_month`, and `status`.

A `ComplianceReviewer` assembles filings as regulatory submissions. Creation names the `facility_id` and a `submission_type` of `MONTHLY_RELEASE_DETECTION`, `TEST_REPORT`, or `RELEASE_NOTIFICATION`, and each type demands its own bundle. A monthly release-detection filing requires `period_month` and a non-empty `release_detection_record_ids`, where every bundled record must belong to a tank of the facility and match the filing's `period_month`. A test report requires a non-empty `service_order_ids`, every one of which must be `CERTIFIED` and belong to the facility. A release notification requires `release_event_id`, belonging to the facility. A bundle that is missing for its type, contains items of another facility, or contains items in the wrong state is rejected with `ERR_BUNDLE_ITEM_MISMATCH`. The new submission sits in `DRAFT` with `submitted_at` null and `is_late` false, and bundle fields that do not apply to its type are stored and returned as null (`period_month`, `release_event_id`) or as empty arrays (`release_detection_record_ids`, `service_order_ids`); submissions list by `facility_id`, `submission_type`, `release_event_id`, and `status`.

Submitting a draft (`ERR_SUBMISSION_NOT_DRAFT` from any other status) stamps `submitted_at` with the logical clock and computes lateness: for a monthly filing, `is_late` is true when `submitted_at` falls after the period's due timestamp — 23:59:59.999 on the 10th day of the month following the `period_month` — and for the other filing types `is_late` is false. Submission also moves every bundled release-detection record from `RECORDED` to `SUBMITTED`.

The `StateRegulator` then disposes of the filing from `SUBMITTED` (`ERR_SUBMISSION_NOT_SUBMITTED` otherwise). Acceptance moves the submission to its terminal `ACCEPTED` state and every bundled record to `ACCEPTED`. Rejection takes a `note`, stores it as `state_reviewer_note`, moves the submission to `REJECTED`, and compensates by returning every bundled record to `RECORDED`. A rejected filing is not dead: the reviewer may amend it back to `DRAFT` (`ERR_SUBMISSION_NOT_REJECTED` otherwise), carrying `expected_submission_version` per §2.8 with stale amendments rejected as `ERR_STALE_VERSION`. The amendment replaces the provided bundle fields — `period_month`, `release_detection_record_ids`, `service_order_ids`, or `release_event_id` — re-validated under the same type rules as creation (`ERR_BUNDLE_ITEM_MISMATCH`, `ERR_INVALID_REQUEST`), and resets `submitted_at` to null and `is_late` to false — the prior `state_reviewer_note` is retained — so the filing can be submitted afresh.

### 3.7. Operator Training and Class A/B/C Credentialing

Regulations require trained operators on site. The owner designates an operator for a facility with `facility_id`, `full_name`, and an `operator_class` of `A`, `B`, or `C`; designations enter in `DESIGNATED` status and list by `facility_id`, `operator_class`, and `status`.

Credentials are training records, issued by field staff with teaching authority. Issuing a certificate is a `Technician`-role action in which the caller's `X-User-ID` must identify a registered Technician (`ERR_TECHNICIAN_NOT_FOUND`) whose `trainer` flag is true (`ERR_INSTRUCTOR_NOT_TRAINER`); it takes `operator_id`, `course_class`, and `completed_at`, and stamps `instructor_technician_id` from the caller's `X-User-ID`. The `course_class` must equal the operator's own `operator_class` (`ERR_CLASS_MISMATCH`), and `completed_at` must not lie in the future relative to the logical clock (`ERR_INVALID_REQUEST`). The certificate's `expires_at` is computed at issuance: `completed_at` plus 36 months for class `A`, 36 months for class `B`, and 12 months for class `C`. A certificate is valid only while the logical clock is strictly before `expires_at`; at exactly `expires_at` the credential is already expired. Training records list by `operator_id`, `instructor_technician_id`, and `course_class`.

Activation turns a designation into a working credential. The owner may activate an operator in `DESIGNATED` or `LAPSED` status (`ERR_OPERATOR_NOT_ACTIVATABLE` otherwise). Activation demands a training record matching the operator's class; when several exist, the system selects the one with the latest `completed_at`, breaking ties in favor of the most recently created record. If no record exists for the class, activation fails with `ERR_TRAINING_MISSING`; if the selected record's `expires_at` is at or before the logical clock, it fails with `ERR_TRAINING_EXPIRED`. A successful activation moves the operator to `ACTIVE` and recomputes the facility posture.

Credentials decay on their own. At each monthly close, every `ACTIVE` operator whose latest training record for their class — selected by the same latest-`completed_at`, tie-break most-recently-created rule — has expired lapses to `LAPSED`, costing the facility posture points. And the owner may revoke an operator at any time: revocation from `DESIGNATED`, `ACTIVE`, or `LAPSED` always succeeds and moves the operator to the terminal `REVOKED` state, with a posture recompute, while revoking an already `REVOKED` operator is rejected with `ERR_OPERATOR_NOT_ACTIVATABLE`. Revocation also arrives via facility closure.

### 3.8. Suspected Releases and State Fund Reimbursement

When something escapes a tank, the clock starts immediately. The owner reports a suspected release with `facility_id`, an optional `tank_system_id` identifying the source tank when known — when supplied it must identify an existing tank (`ERR_TANK_SYSTEM_NOT_FOUND`) but is not otherwise checked against the named facility — the `discovered_at` timestamp of first suspicion, and a free-text `source_description`. The event enters in `SUSPECTED` status with a `report_deadline` of `discovered_at` plus 24 hours, and the facility posture is recomputed to reflect the new open release. Recall from §3.4 that a failed tightness test also opens a `SUSPECTED` release automatically. Release events list by `facility_id`, `tank_system_id`, and `status`.

The `StateRegulator` disposes of a suspicion from `SUSPECTED` (`ERR_RELEASE_NOT_SUSPECTED` otherwise) in one of two directions, and either way stamps `reported_to_state_at` with the logical clock and computes `late_notification` — true only when the report reached the state strictly after the 24-hour `report_deadline`. Confirming the release moves it to `CONFIRMED` and triggers the tank cascade: when `tank_system_id` is set and that tank is not already `PERMANENTLY_CLOSED`, the tank moves to `TEMPORARILY_CLOSED`, its `REQUESTED` and `SCHEDULED` orders are cancelled, and their linked re-test deficiencies fall back to `CORRECTED`; the posture recompute keeps the open-release penalty. Dismissing the release moves it to `DISMISSED`, terminal, and the posture recompute removes the penalty as the release exits the open set. Cleanup proceeds under shared custody: the owner moves a `CONFIRMED` release to `CLEANUP_IN_PROGRESS` (`ERR_RELEASE_NOT_CONFIRMED` otherwise), and the regulator closes it from `CLEANUP_IN_PROGRESS` to `CLOSED` (`ERR_RELEASE_NOT_CLEANUP` otherwise), again lifting the posture penalty.

Cleanup costs are recoverable from the state fund. The owner opens a fund claim with `facility_id`, the `release_event_id` it compensates, and a non-empty `expense_lines` array whose lines each carry a `description` and an integer `amount_cents` greater than zero (an empty array or a non-positive amount is `ERR_INVALID_REQUEST`). Creation is gated, in the validation precedence of §2.7: the facility's `compliance_posture` must not be `NON_COMPLIANT` (`ERR_FACILITY_POSTURE_BLOCKS_CLAIM`); the release must belong to the same facility (`ERR_CLAIM_RELEASE_MISMATCH`); the release must be `CONFIRMED`, `CLEANUP_IN_PROGRESS`, or `CLOSED` (`ERR_CLAIM_RELEASE_NOT_CONFIRMED`); the facility's `annual_fee_paid_through` must be at or after the logical clock (`ERR_FEES_NOT_CURRENT`); and the computed payable must fit within the facility's `fund_cap_remaining_cents` (`ERR_FUND_CAP_EXCEEDED`).

The claim's money fields are computed at creation from the expense total. Let the total be the sum of `amount_cents` across all expense lines. Under the `PER_OCCURRENCE` election, `deductible_applied_cents` is the lesser of the expense total and the fixed per-occurrence deductible of 1000000 cents (ten thousand dollars); `eligible_amount_cents` is the expense total minus the deductible, floored at zero; and `payable_amount_cents` is the eligible amount multiplied by a coinsurance rate of 0.90, with the single product rounded half-up to whole cents. Under the `AGGREGATE` election, `deductible_applied_cents` is instead the lesser of the expense total and the facility's remaining `fund_year_deductible_remaining_cents` pool; `eligible_amount_cents` is the expense total minus that deductible; and `payable_amount_cents` equals the eligible amount in full — the fund pays 100% once the aggregate deductible is exhausted. Identical expense lines therefore yield different payables under the two elections. The payable is a gross figure; the fund-year cap is enforced separately, at submission. The new claim enters in `DRAFT` with `approved_amount_cents` null.

Submitting a claim moves it `DRAFT` → `SUBMITTED` (`ERR_CLAIM_NOT_DRAFT` otherwise), re-checks the payable against `fund_cap_remaining_cents` (`ERR_FUND_CAP_EXCEEDED`), and reserves the money by subtracting `payable_amount_cents` from the facility's cap. Withdrawal is the owner's escape hatch from `DRAFT` or `SUBMITTED` (`ERR_CLAIM_NOT_WITHDRAWABLE` otherwise), moving the claim to the terminal `WITHDRAWN` state: withdrawing a `SUBMITTED` claim releases the reservation, adding `payable_amount_cents` back to the cap, while withdrawing a `DRAFT` claim releases nothing because nothing was reserved. Adjudication belongs to the `StateRegulator` and requires `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`); the regulator supplies a `decision` of `APPROVED`, `PARTIALLY_APPROVED`, or `DENIED` — the claim's terminal status becomes the decision value — and for a partial approval an explicit `approved_amount_cents` lying strictly between zero and the payable (`ERR_INVALID_REQUEST` outside that range). An approval sets `approved_amount_cents` equal to `payable_amount_cents` and consumes the reservation; a partial approval sets it to the supplied value and releases the unused difference back into the cap; a denial sets it to zero and releases the entire reservation. Under the `AGGREGATE` election, both approval and partial approval also consume the deductible by subtracting `deductible_applied_cents` from the facility's `fund_year_deductible_remaining_cents`. Claims list by `facility_id`, `release_event_id`, and `status`.

### 3.9. The Monthly Close Sweep

Once a month, a `ContractorAdmin` runs the close checkpoint for one facility and one `period_month`. The facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), and the close is only timely once the books for the period can no longer change: the logical clock must be at or after 00:00:00 on the 11th day of the month following the `period_month` — earlier runs are rejected with `ERR_CLOSE_TOO_EARLY`. Symmetrically, a period's records count as on time when they were recorded while the clock was at or before 23:59:59.999 on the 10th day of the following month, which is the same boundary the monthly filing's `is_late` flag measures against.

The sweep executes four steps in a pinned order. First, the missing-record sweep: for each tank of the facility in `IN_SERVICE` or `TEMPORARILY_CLOSED`, taken in creation order, if no release-detection record exists for that tank and `period_month`, the system opens a `MINOR` deficiency of origin `CLOSE_SWEEP` carrying that `period_month` — unless a deficiency with the same tank, origin, and period already exists, which makes re-running a close idempotent. Second, the operator lapse sweep of §3.7 lapses every `ACTIVE` operator whose latest class certificate has expired. Third, the escalation sweep of §3.5 escalates every non-terminal deficiency whose `correction_deadline` has passed. Fourth — and only after the first three steps complete — the facility's `posture_score` and `compliance_posture` are recomputed exactly once. The checkpoint returns the counts it produced: `deficiencies_created`, `operators_lapsed`, `deficiencies_escalated`, plus the refreshed `posture_score` and `compliance_posture`.

## 4. Endpoint Definitions

Endpoints that create a new resource — registering a facility, tank, component, technician, service order, submission, record, operator, training record, release event, or fund claim — return `201 Created`. Endpoints that modify an existing resource, including all state transitions, edits, and the clock-setting capability, return `200 OK`. Readers reconstruct each endpoint's full request and response contract from the workflow narratives in §3 together with the global rules in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ContractorAdmin |
| POST | `/facilities` | Register a facility | FacilityOwner |
| GET | `/facilities` | List facilities | Any |
| GET | `/facilities/{id}` | Get one facility | Any |
| POST | `/facilities/{id}/activate` | Activate a registered facility | FacilityOwner |
| POST | `/facilities/{id}/close` | Close an active facility | FacilityOwner |
| POST | `/facilities/{id}/run-monthly-close` | Run the monthly close sweep for a period | ContractorAdmin |
| POST | `/tank-systems` | Register a tank system for a facility | FacilityOwner |
| GET | `/tank-systems` | List tank systems | Any |
| GET | `/tank-systems/{id}` | Get one tank system | Any |
| GET | `/tank-systems/{id}/test-schedule` | Project the tank's upcoming test due dates | Any |
| POST | `/tank-systems/{id}/place-in-service` | Place a registered tank in service | FacilityOwner |
| POST | `/tank-systems/{id}/close` | Close a tank temporarily or permanently | FacilityOwner |
| POST | `/tank-systems/{id}/return-to-service` | Return a temporarily closed tank to service | FacilityOwner |
| POST | `/components` | Add a component to a tank | FacilityOwner |
| GET | `/components` | List components | Any |
| GET | `/components/{id}` | Get one component | Any |
| POST | `/technicians` | Register a contractor technician | ContractorAdmin |
| GET | `/technicians` | List technicians | Any |
| GET | `/technicians/{id}` | Get one technician | Any |
| POST | `/service-orders` | Create a service order with a computed quote | ContractorAdmin |
| GET | `/service-orders` | List service orders | Any |
| GET | `/service-orders/{id}` | Get one service order | Any |
| POST | `/service-orders/{id}/schedule` | Assign technician and window to an order | ContractorAdmin |
| PUT | `/service-orders/{id}` | Edit line items, window, or technician of an order | ContractorAdmin |
| POST | `/service-orders/{id}/start` | Start an assigned order inside its window | Technician |
| POST | `/service-orders/{id}/results` | Record test readings and compute the outcome | Technician |
| POST | `/service-orders/{id}/certify` | Certify a reviewed order | ComplianceReviewer |
| POST | `/service-orders/{id}/return-for-correction` | Return a reviewed order for rework | ComplianceReviewer |
| POST | `/service-orders/{id}/cancel` | Cancel a requested or scheduled order | ContractorAdmin |
| GET | `/result-records` | List result records | Any |
| GET | `/result-records/{id}` | Get one result record | Any |
| GET | `/deficiencies` | List deficiencies | Any |
| GET | `/deficiencies/{id}` | Get one deficiency | Any |
| POST | `/deficiencies/{id}/order-correction` | Order correction of an open or escalated deficiency | FacilityOwner |
| POST | `/deficiencies/{id}/mark-corrected` | Mark an ordered deficiency corrected | FacilityOwner |
| POST | `/submissions` | Create a draft regulatory submission | ComplianceReviewer |
| GET | `/submissions` | List submissions | Any |
| GET | `/submissions/{id}` | Get one submission | Any |
| POST | `/submissions/{id}/submit` | Submit a draft filing | ComplianceReviewer |
| POST | `/submissions/{id}/accept` | Accept a submitted filing | StateRegulator |
| POST | `/submissions/{id}/reject` | Reject a submitted filing with a note | StateRegulator |
| POST | `/submissions/{id}/amend` | Amend a rejected filing back to draft | ComplianceReviewer |
| POST | `/release-detection-records` | Record a tank's monthly release-detection record | FacilityOwner |
| GET | `/release-detection-records` | List release detection records | Any |
| GET | `/release-detection-records/{id}` | Get one release detection record | Any |
| POST | `/operators` | Designate a Class A/B/C operator | FacilityOwner |
| GET | `/operators` | List operators | Any |
| GET | `/operators/{id}` | Get one operator | Any |
| POST | `/operators/{id}/activate` | Activate a designated or lapsed operator | FacilityOwner |
| POST | `/operators/{id}/revoke` | Revoke an operator | FacilityOwner |
| POST | `/training-records` | Issue a training certificate to an operator | Technician |
| GET | `/training-records` | List training records | Any |
| GET | `/training-records/{id}` | Get one training record | Any |
| POST | `/release-events` | Report a suspected release | FacilityOwner |
| GET | `/release-events` | List release events | Any |
| GET | `/release-events/{id}` | Get one release event | Any |
| POST | `/release-events/{id}/confirm` | Confirm a suspected release | StateRegulator |
| POST | `/release-events/{id}/dismiss` | Dismiss a suspected release | StateRegulator |
| POST | `/release-events/{id}/begin-cleanup` | Begin cleanup on a confirmed release | FacilityOwner |
| POST | `/release-events/{id}/close` | Close a release under cleanup | StateRegulator |
| POST | `/fund-claims` | Create a draft state fund claim | FacilityOwner |
| GET | `/fund-claims` | List fund claims | Any |
| GET | `/fund-claims/{id}` | Get one fund claim | Any |
| POST | `/fund-claims/{id}/submit` | Submit a claim and reserve against the fund cap | FacilityOwner |
| POST | `/fund-claims/{id}/withdraw` | Withdraw a draft or submitted claim | FacilityOwner |
| POST | `/fund-claims/{id}/adjudicate` | Adjudicate a submitted claim | StateRegulator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SELF_CERTIFICATION` | 403 Forbidden |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_TANK_SYSTEM_NOT_FOUND` | 404 Not Found |
| `ERR_COMPONENT_NOT_FOUND` | 404 Not Found |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_RESULT_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_DEFICIENCY_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_OPERATOR_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_RELEASE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_FUND_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_TANK_REGISTERED` | 409 Conflict |
| `ERR_TANKS_NOT_CLOSED` | 409 Conflict |
| `ERR_TANK_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_ORDER_NOT_REQUESTED` | 409 Conflict |
| `ERR_ORDER_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ORDER_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_ORDER_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_EDITABLE` | 409 Conflict |
| `ERR_DEFICIENCY_NOT_OPEN` | 409 Conflict |
| `ERR_DEFICIENCY_NOT_ORDERED` | 409 Conflict |
| `ERR_SUBMISSION_NOT_DRAFT` | 409 Conflict |
| `ERR_SUBMISSION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_SUBMISSION_NOT_REJECTED` | 409 Conflict |
| `ERR_RELEASE_NOT_SUSPECTED` | 409 Conflict |
| `ERR_RELEASE_NOT_CONFIRMED` | 409 Conflict |
| `ERR_RELEASE_NOT_CLEANUP` | 409 Conflict |
| `ERR_CLAIM_NOT_DRAFT` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_OPERATOR_NOT_ACTIVATABLE` | 409 Conflict |
| `ERR_CRITICAL_DEFICIENCY_OPEN` | 409 Conflict |
| `ERR_OPEN_RELEASE_ON_TANK` | 409 Conflict |
| `ERR_DUPLICATE_TANK_TAG` | 409 Conflict |
| `ERR_DUPLICATE_RECORD` | 409 Conflict |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_TANK_STABILIZATION_WINDOW` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_SERVICE_WINDOW` | 422 Unprocessable Entity |
| `ERR_CLOSE_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_FUTURE_PERIOD` | 422 Unprocessable Entity |
| `ERR_ENDORSEMENT_MISSING` | 422 Unprocessable Entity |
| `ERR_INSTRUCTOR_NOT_TRAINER` | 422 Unprocessable Entity |
| `ERR_CLASS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TRAINING_MISSING` | 422 Unprocessable Entity |
| `ERR_TRAINING_EXPIRED` | 422 Unprocessable Entity |
| `ERR_MODE_NOT_ALLOWED_FOR_CAPACITY` | 422 Unprocessable Entity |
| `ERR_TANK_FACILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COMPONENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DEFICIENCY_LINK_INVALID` | 422 Unprocessable Entity |
| `ERR_BUNDLE_ITEM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_RELEASE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_RELEASE_NOT_CONFIRMED` | 402 Payment Required |
| `ERR_FEES_NOT_CURRENT` | 402 Payment Required |
| `ERR_FUND_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_FACILITY_POSTURE_BLOCKS_CLAIM` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INTERNAL` | 500 Internal Server Error |
