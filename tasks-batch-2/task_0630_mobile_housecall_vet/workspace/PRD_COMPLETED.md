# Mobile & House-Call Veterinary Service API — Product Requirements Document

## 1. Introduction

Mobile veterinary practices in the style of The Vets and Bond Vet bring the clinic to the client's front door: a clinician and a stocked vehicle travel a planned route, delivering wellness exams, vaccinations, and — where local ordinance permits — in-home euthanasia. This API is the operational backbone of such a practice. It coordinates the people who provide care, the vehicles that carry the medicine, the geographic areas the practice is licensed to serve, and the appointments that tie them together, while holding the whole operation to the documentation and accountability standards that controlled substances demand.

The system's hardest problems are not scheduling conveniences but compliance and reconciliation. Every milligram of a controlled euthanasia drug must be drawn, witnessed, wasted, and counted by people with the right credentials, and an independent recount at the end of each route must agree with the running tally to the tenth of a milliliter. Routes must be packed densely enough to be economical yet never double-book a clinician who cannot teleport between homes nor a single van across two simultaneous routes. Estimates are quoted optimistically before a visit and re-derived conservatively afterward against what was actually administered, and the client pays the exact reconciled figure on site. This document specifies the entities, lifecycles, calculations, and guardrails that make those guarantees enforceable, written for the engineers who will implement them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that govern every endpoint. Where a rule below references a specific business workflow, the full narrative for that workflow lives in §3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting principal, and the `X-User-Role` header declares the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_AUTH`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly three roles, spelled precisely as follows: `Dispatcher`, `Clinician`, and `ComplianceOfficer`. A `Dispatcher` runs the back office — booking appointments, building and locking route days, and managing patients, vehicles, service areas, and wellness plans. A `Clinician` is the person on the doorstep — the one who arrives, prices and approves the work, records controlled-med entries, takes payment, handles specimens, and refers cases out. A `ComplianceOfficer` provides controlled-substance oversight — reconciling and closing routes and acknowledging referrals — and may read the full controlled-substance audit trail.

The identity semantics of each role differ. When `X-User-Role` is `Clinician`, `X-User-ID` is the `id` of the acting `Clinician` entity; any ownership check on a resource that references a `Clinician` compares the resource's clinician foreign key to `X-User-ID`. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded if useful but never matched against an entity's `id`. All three roles share read access: any `GET` collection or item endpoint may be called by a `Dispatcher`, a `Clinician`, or a `ComplianceOfficer`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the count of leading items to skip and defaults to 0.

Unless an endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order. Every list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Audit Lifecycle

Most resources in the system carry a common set of server-managed fields. The `id` is a server-minted UUID used purely for identity; it carries no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first persisted. The `updated_at` field is an ISO 8601 UTC timestamp, also with three fractional digits, refreshed on every mutation of the resource. The `version` field is an integer that starts at 1 on creation and increases by exactly 1 on every mutation.

One entity is deliberately leaner. A `ControlledMedLog` entry is an append-only record: it carries only an `id` and a `created_at` and has neither an `updated_at` nor a `version`, because it is never modified after it is written. Its `created_at` doubles as the entry timestamp that orders the controlled-substance ledger. Every other entity — `ServiceArea`, `Clinician`, `RollingClinic`, `Patient`, `Appointment`, `RouteDay`, `RouteStop`, `Estimate`, `Payment`, `SpecimenPickup`, `WellnessPlan`, and `Referral` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

Whenever a derived or computed field is recomputed as a consequence of some action — a route day's `stop_count`, a vehicle's `controlled_reconciled_ml`, an estimate's totals — that recomputation is itself a mutation of the owning resource, refreshing its `updated_at` and incrementing its `version`. When one operation cascades into a second entity (for example, booking a stop also touches the route day), each affected entity independently advances its own `updated_at` and `version`.

### 2.5. Nested Resource Retrieval and Referential Integrity

Several endpoints address a resource through a path that names a parent before a child — for instance, listing or creating the stops that belong to a particular route day, or appending a controlled-med entry under a particular appointment. The server validates path identifiers strictly left to right: the parent named earliest in the path is resolved first, and the first identifier that does not resolve to an existing resource causes the request to fail immediately with `ERR_NOT_FOUND`, before any later identifier or body reference is examined. After the path is cleared, foreign-key identifiers carried in the request body are resolved in their declaration order, again surfacing `ERR_NOT_FOUND` on the first that does not resolve.

### 2.6. Validation Order and Precedence

When several checks could reject a single request, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. Authentication comes first: a missing or malformed header yields `ERR_MISSING_AUTH`. Authorization comes second: a role not permitted for the operation yields `ERR_FORBIDDEN_ROLE`. Existence comes third: an unresolved path or body foreign key yields `ERR_NOT_FOUND`. Only after these three gates does the server consider domain rules — state legality, route posture, area coverage, safety, scheduling, stock, fiscal, concurrency, and finally body well-formedness.

Body well-formedness — required fields present, enum values legal, and numeric ranges respected (a `weight_kg` greater than 0, an `amount_ml` greater than 0, a `requested_end` strictly later than `requested_start`, and a `window_end` strictly later than `window_start`) — is reported as `ERR_INVALID_REQUEST`. State-legality failures, where the target resource is not in a status from which the requested transition is allowed, surface as `ERR_INVALID_STATE`; this is the general guard behind the appointment, route, estimate, and specimen lifecycles described in §3, and individual workflows may name a more specific error where the scaffold defines one.

### 2.7. Monetary Precision and Rounding

All money in the system is expressed in integer cents — `travel_surcharge_cents`, `subtotal_cents`, `estimate_total_cents`, `invoice_total_cents`, and a payment's `amount_cents` are all whole-cent integers. Wherever a per-line money figure must be rounded, the system uses round-half-up. The critical discipline for estimate and invoice arithmetic is that rounding happens per line and then the rounded integer cents are summed; the system never sums raw products and rounds once at the end. Because a line's quantity may be fractional while its unit price is in whole cents, this ordering is observable and must be honored exactly as described in §3.

### 2.8. Dosing and Reconciliation Precision

Two controlled-substance calculations work to one decimal place, again using round-half-up: the minimum required euthanasia dose derived from the patient's weight, and the independent end-of-route recount of a vehicle's controlled stock. The reconciliation recount replays the day's controlled-med entries in `created_at` ascending order, with ties broken by `created_at` and never by `id`; the full arithmetic of both calculations is given in §3.

### 2.9. Optimistic Concurrency Control

Two write operations carry an explicit version guard so that a client cannot act on a stale view of a resource. Booking a stop onto a route day requires the body to carry `expected_route_day_version`, holding the `version` of the target `RouteDay` that the client last observed. If that value does not equal the route day's current `version`, the booking is rejected with `ERR_STALE_ROUTE_DAY_VERSION` and HTTP 412. This matters because each successful booking legitimately advances the route day's `version` and re-sequences the route; a second booking still carrying the older version is working from an out-of-date picture of the route's stop set and capacity, and is refused rather than allowed to overwrite a state it never saw. The `expected_route_day_version` field is mandatory on this operation, not optional.

Toggling a vehicle's maintenance flag is likewise guarded: that request must carry `expected_rolling_clinic_version` holding the client's last observed `RollingClinic.version`, and a mismatch with the vehicle's current `version` is refused on the same stale-version basis. No other endpoint accepts or requires a version field.

### 2.10. The Logical Clock

The system runs on a logical clock rather than wall-clock time, so that time-dependent behavior — DEA expiry checks, wellness reminder math — is reproducible. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly moved it never falls back to the host's wall clock. An administrative capability advances the clock to a supplied instant and reports the new `current_utc`; the request supplies the target instant as `to_iso8601`. Every "current clock" reference elsewhere in this document means this logical clock.

## 3. Business Logic & Workflows

### 3.1. Coverage, Fleet, and the People Who Provide Care

Before any visit can be booked, the practice must describe where it operates, who works, and what rolls. A `Dispatcher` defines a **ServiceArea** for each ZIP the practice covers, supplying a `zip_code`, a human `name` such as "Brooklyn North", and a `travel_surcharge_cents` (a flat trip fee, never negative, added to every estimate for visits in that ZIP). The optional `euthanasia_allowed` flag declares whether in-home euthanasia is legally permitted in that ZIP; it defaults to true when not supplied. A new area begins in `ACTIVE` status, and a ZIP must be unique across active areas. A dispatcher may later suspend an area, moving its `status` from `ACTIVE` to `SUSPENDED`, which stops new bookings in that ZIP.

A **Clinician** is registered by a dispatcher with a `full_name` and a `clinician_role` of either `VET` or `TECH`. The distinction is load-bearing: only a `VET` may administer controlled drugs and sign for euthanasia. When the role is `VET`, a `dea_number` and a `dea_expires_on` date (a UTC-midnight instant) are required; when the role is `TECH`, both must be null. Every clinician starts in `AVAILABLE` status and moves through `ON_ROUTE` and back to `AVAILABLE` as routes run, and may be taken `OFF_DUTY`.

A **RollingClinic** is the van. A dispatcher creates one with a `plate` label and its starting inventory: `controlled_stock_ml`, the on-board pentobarbital in milliliters (never negative, and mutated downward as controlled-med entries are recorded), and `vaccine_stock_count`, the on-board non-controlled vaccine doses (never negative, and decremented as vaccines are administered). The vehicle also exposes a computed `controlled_reconciled_ml`, an independent recount produced at route close (see §3.7); it is null on creation and stays null until a reconciliation populates it. A van starts `IN_DEPOT` and moves through `DEPLOYED` and back as routes lock and reconcile. A dispatcher may flag a van for maintenance; that request carries the desired `status` (which must be exactly `MAINTENANCE` or `IN_DEPOT`) plus the concurrency guard `expected_rolling_clinic_version`, toggles the vehicle between `MAINTENANCE` and `IN_DEPOT`, and increments the vehicle's `version`. A mismatch between `expected_rolling_clinic_version` and the vehicle's current `version` is refused with `ERR_STALE_ROUTE_DAY_VERSION` and HTTP 412 — the same error identifier the route-day booking guard uses.

A **Patient** pairs an animal with its owner. A dispatcher records an `owner_name`, a `species` of `DOG`, `CAT`, or `OTHER`, a `weight_kg` that must be strictly greater than 0 (this weight drives euthanasia dosing), and a `home_zip` that is matched against service-area coverage when visits are booked.

### 3.2. Requesting a Visit

A `Dispatcher` opens the appointment lifecycle by creating an **Appointment** that names the `patient_id`, a `visit_type` of `EXAM`, `VACCINE`, or `EUTHANASIA`, and a requested window bounded by `requested_start` and `requested_end`, where the end must fall strictly after the start. When the visit is a vaccination, the dispatcher also supplies `vaccine_doses`, the number of doses to administer; this field defaults to 0 and is only meaningful for a `VACCINE` visit. At creation the appointment's `service_area_id` is resolved by matching the patient's `home_zip` to the `zip_code` of an `ACTIVE` service area, and the appointment enters `REQUESTED` status; if no `ACTIVE` area covers the ZIP, creation still succeeds with `service_area_id` stored as null, and coverage is enforced only later at booking and estimate time.

An `EUTHANASIA` appointment forks the rest of the lifecycle: it pulls in the controlled-substance flow described in §3.5 and §3.7, and it cannot be referred out (see §3.6). The remaining visit types follow the simpler path through estimate, visit, and payment.

### 3.3. Building and Locking a Route

A route is a clinician, a van, and a calendar date. A `Dispatcher` creates a **RouteDay** naming the `clinician_id`, the `rolling_clinic_id`, and the `service_date` (a UTC-midnight date). It begins with a `posture` of `OPEN` and a `stop_count` of 0. Posture governs what the route will accept: `OPEN` accepts new stops, `LOCKED` freezes the stop set for the day, and `RECONCILED` is the terminal state after the controlled-med count closes.

Booking an appointment onto a route is the act that schedules it. A dispatcher creates a **RouteStop** against an open route day, supplying the `appointment_id` to service, the planned `window_start` and `window_end` (end strictly after start), and the mandatory `expected_route_day_version`. This single operation drives the appointment from `REQUESTED` to `SCHEDULED` and is gated by a layered set of preconditions. The route day must be `OPEN`, or the booking is refused with `ERR_ROUTE_NOT_OPEN`. The appointment's resolved service area — found from the patient's `home_zip` — must be `ACTIVE`, or the booking is refused with `ERR_AREA_NOT_COVERED`. If the visit is an `EUTHANASIA`, that service area's `euthanasia_allowed` must be true, or the booking is refused with `ERR_EUTHANASIA_NOT_PERMITTED`; additionally the route day's clinician must have a `clinician_role` of `VET`, or the booking is refused with `ERR_VET_REQUIRED`.

Two scheduling-geometry checks then apply, both treating each window as the half-open interval from its start up to but not including its end, and both ignoring any stop already in `SKIPPED`. The first is a clinician-travel check on the same route day: because one clinician cannot teleport between homes, two windows conflict not only when they overlap but also when the gap between them is smaller than the travel buffer of 30 minutes. Concretely, the proposed stop conflicts with an existing stop when the proposed start falls earlier than the existing end extended forward by 30 minutes, and at the same time the existing start falls earlier than the proposed end extended forward by 30 minutes; two windows that merely touch end-to-start, with a zero-minute gap, therefore do conflict because the buffer is positive. This conflict is reported as `ERR_STOP_WINDOW_CONFLICT`. The second is a vehicle double-booking check across any other route day that shares the same `rolling_clinic_id` on the same `service_date`, applied with a zero buffer: the proposed stop conflicts with such a stop when the proposed start falls earlier than the other's end and the other's start falls earlier than the proposed end. Here touching exactly at an endpoint — proposed start equal to the other's end — does not conflict, because the van can be handed off instantly. This conflict is reported as `ERR_VEHICLE_DOUBLE_BOOKED`.

When all of these pass, the system records the booking against the most current route day. The concurrency guard described in §2.9 is what makes "most current" precise: the supplied `expected_route_day_version` must equal the route day's present `version`, failing which the booking is rejected with `ERR_STALE_ROUTE_DAY_VERSION`. A successful booking creates the route stop in `PLANNED` status, advances the appointment to `SCHEDULED`, recomputes the route day's `stop_count`, recomputes the `sequence` of every stop on the route, and increments the route day's `version` by 1.

The route day's `stop_count` is, at all times, the number of its route stops whose status is `PLANNED`, `ARRIVED`, or `SERVICED`; stops in `SKIPPED` are excluded from the count. The `sequence` is a one-based ordinal assigned across all non-`SKIPPED` stops on the route, ordered by `window_start` ascending and, where two windows start at the same instant, by `created_at` ascending — never by `id`. A stop that becomes `SKIPPED` keeps whatever sequence it last held and is not renumbered; the remaining non-`SKIPPED` stops are renumbered from 1.

Once a route is built, a dispatcher locks it, moving its `posture` from `OPEN` to `LOCKED`; a route whose `posture` is not `OPEN` cannot be locked and the attempt is refused with `ERR_ROUTE_NOT_OPEN`. Locking requires that the route already hold at least one counted stop — a `stop_count` of 1 or more — or it is refused with `ERR_ROUTE_EMPTY`. The assigned vehicle must not be in `MAINTENANCE`, or the lock is refused with `ERR_VEHICLE_UNAVAILABLE`. Locking freezes the stop set so that no further stops may be created while the route is `LOCKED`, moves the vehicle from `IN_DEPOT` to `DEPLOYED`, and moves the clinician to `ON_ROUTE`.

### 3.4. Pricing the Work: Estimates and the Two-Variant Total

A `Clinician` prices a visit by creating an **Estimate** against the `appointment_id`, supplying `line_items` as an array of objects each carrying a `code`, a human `label`, a `unit_cents` unit price, and a `qty` quantity. The estimate begins in `DRAFT` status. From its line items the system derives the money fields bottom-up. Each line's contribution is the unit price multiplied by the quantity, rounded half-up to whole cents on that line alone; `subtotal_cents` is the running sum of those per-line rounded amounts, accumulated in the array order of the line items. The system then reads the `travel_surcharge_cents` from the service area resolved through the appointment's patient — re-resolved from the patient's `home_zip` to an `ACTIVE` area, and if no `ACTIVE` area covers that ZIP the estimate is refused with `ERR_AREA_NOT_COVERED` — and copies it onto the estimate, and `estimate_total_cents` is the subtotal plus that travel surcharge. Because a quantity may be fractional — 1.5 vials, say — while the unit price is whole cents, the per-line rounding is observable, and the system must round each line before summing rather than summing raw products and rounding once.

While an estimate is still `DRAFT`, a clinician may revise it, replacing the `line_items` wholesale; each revision recomputes `subtotal_cents` and `estimate_total_cents` by the same per-line rule and increments the estimate's `version`. A clinician approves a `DRAFT` estimate to move it to `APPROVED`, which locks the line items against further revision; approval is only allowed while the linked appointment is in `SCHEDULED` or `IN_VISIT`, and otherwise fails with `ERR_APPT_NOT_IN_VISIT_PHASE`. The estimate's `invoice_total_cents` remains unset until the visit closes.

The forward-looking estimate total and the backward-looking invoice total are two variants of one calculation. At estimate time, before the visit, every line is billed at its full requested quantity — an optimistic projection of the full plan. At visit close, after administration, the invoice is re-derived: it walks the same locked line items in array order, but a line whose `code` is `VACCINE_DOSE` is billed not for its full quantity but for the lesser of its quantity and the doses the appointment actually administered (its `vaccine_doses`); every other line bills its full quantity. Each line is again rounded half-up before summing, and the travel surcharge already stored on the estimate is added to produce `invoice_total_cents`. Because partial vaccine delivery caps the billable vaccine quantity, the invoice total can come out strictly below the estimate total.

### 3.5. The Visit, the Controlled-Med Ledger, and Closing Out

When the clinician reaches the door, arrival opens the on-site phase: a `Clinician` records arrival, which is legal only while the appointment is `SCHEDULED` and its linked route stop is `PLANNED`, and only while the route day's `posture` is `OPEN` or `LOCKED` (otherwise `ERR_ROUTE_NOT_OPEN`). Arrival advances the appointment from `SCHEDULED` to `IN_VISIT`, flips the linked route stop from `PLANNED` to `ARRIVED`, and sets the clinician to `ON_ROUTE`.

For a euthanasia visit, the controlled-substance ledger is built during the `IN_VISIT` phase. A clinician appends entries to the **ControlledMedLog** for the appointment, each naming the `rolling_clinic_id` of the van whose stock it adjusts, the `administering_vet_id` of the vet who drew and gave the drug, an `entry_type`, and the `amount_ml` involved (strictly greater than 0). An entry of type `DISPENSE` documents the administered dose; an entry of type `WASTE` documents the co-signed disposal of the unused remainder, and a `WASTE` entry must additionally name a `witness_vet_id`. Several safety gates protect every entry. The administering party — and, for waste, the witness — must be a `VET` whose `dea_number` is present and whose `dea_expires_on` has not passed against the current clock; a non-vet, or a vet with an absent or expired registration, is rejected with `ERR_DEA_INVALID`. On a `WASTE` entry the `witness_vet_id` must differ from the `administering_vet_id`, enforcing segregation of duties, or the entry is rejected with `ERR_WITNESS_CONFLICT`. The van must hold enough controlled stock for the entry — its `controlled_stock_ml` at least the entry's `amount_ml` — or the entry is rejected with `ERR_INSUFFICIENT_STOCK`. Each accepted entry appends to the log and decrements the vehicle's `controlled_stock_ml` by the entry's `amount_ml`; the log entry itself is append-only and immutable.

The minimum legal dose is computed from the patient's weight. The required volume is the patient's `weight_kg` multiplied by a per-kilogram dose of 0.2 milliliters, with a hard floor of 1.0 milliliter for very small animals — that is, the required volume is the larger of the weight-derived figure and the 1.0-milliliter floor, expressed to one decimal place using round-half-up. At a weight of exactly 5.0 kilograms the weight-derived figure equals the floor at 1.0 milliliter; below that weight the floor governs. A `DISPENSE` entry whose `amount_ml` is less than this required floor is rejected with `ERR_DOSE_BELOW_MINIMUM`; a vet may always draw more than the floor, and the overage is later recorded as `WASTE`.

A clinician closes the clinical visit, moving the appointment from `IN_VISIT` to `AWAITING_PAYMENT`. Closing requires that an `APPROVED` estimate exist for the appointment, or it fails with `ERR_NO_APPROVED_ESTIMATE`. For a euthanasia visit, the controlled-med ledger must be complete — both a `DISPENSE` entry and a `WASTE` entry must exist for the appointment — or closing fails with `ERR_EUTHANASIA_LOG_INCOMPLETE`. For a vaccine visit carrying a positive `vaccine_doses`, the van must hold at least that many doses in `vaccine_stock_count`, failing which the stock guard `ERR_INSUFFICIENT_STOCK` applies. Closing the visit finalizes the estimate, moving it from `APPROVED` to `INVOICED` and computing its `invoice_total_cents` by the invoice variant of §3.4. When the visit was a vaccination, the van's `vaccine_stock_count` is decremented by the administered `vaccine_doses`, cascading the vehicle inventory. The linked route stop flips from `ARRIVED` to `SERVICED`, and the route day's `stop_count` is recomputed.

On-site payment settles the visit. A clinician captures a **Payment** naming the `estimate_id` being paid, the `amount_cents` tendered (strictly greater than 0), and a `method` of `CARD`, `CASH`, or `CHECK`. Payment is legal only while the appointment is `AWAITING_PAYMENT` and the estimate is `INVOICED`, and the tendered `amount_cents` must equal the estimate's `invoice_total_cents` exactly — no overpayment or underpayment — or the payment is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A captured payment is created in `CAPTURED` status — the other recognized payment status, `REFUNDED`, is reserved for reversed payments — advances the appointment from `AWAITING_PAYMENT` to `COMPLETED`, and returns the clinician to `AVAILABLE`.

### 3.6. Referrals and Cancellations

Sometimes a case must leave the mobile setting. A `Clinician` refers an appointment that is currently `REQUESTED`, `SCHEDULED`, or `IN_VISIT`, supplying the receiving `hospital_name` and a clinical `reason`. Referral is forbidden for a euthanasia visit — an `EUTHANASIA` appointment cannot be referred, and the attempt is rejected with `ERR_EUTHANASIA_NOT_REFERABLE`. A successful referral drives the appointment to the terminal `REFERRED` status and creates a **Referral** in `OPEN` status. Its cascades resolve the rest of the visit: if the appointment has a linked route stop that is not already in a terminal stop state, that stop flips to `SKIPPED`, and the route day's `stop_count` is recomputed and the route re-sequenced; any `DRAFT` or `APPROVED` estimate for the appointment is voided to `VOID`; and if the clinician was `ON_ROUTE` for this appointment, the clinician returns to `AVAILABLE`. A `ComplianceOfficer` later acknowledges a referral, moving it from `OPEN` to `ACKNOWLEDGED`.

A `Dispatcher` cancels an appointment that is still `REQUESTED` or `SCHEDULED`, driving it to the terminal `CANCELLED` status. Cancellation mirrors the booking cleanup: if a linked route stop is in `PLANNED`, it flips to `SKIPPED`, and the route day's `stop_count` is recomputed and the route re-sequenced; any `DRAFT` or `APPROVED` estimate for the appointment is voided to `VOID`.

### 3.7. Closing the Route: Reconciliation of Controlled Stock

A route closes in two postures. A locked route can only be reconciled once every one of its stops has reached a terminal stop state — every route stop in `SERVICED` or `SKIPPED` — otherwise reconciliation is refused with `ERR_STOPS_OPEN`. A `ComplianceOfficer` performs the reconciliation, moving the route day's `posture` from `LOCKED` to `RECONCILED`; a route day whose `posture` is not `LOCKED` cannot be reconciled and the attempt is refused with `ERR_ROUTE_NOT_OPEN`, checked before the open-stops gate.

Reconciliation is a deliberate double-count of the controlled drug. Throughout the day, the dispense and waste side effects maintained a running balance by decrementing the van's `controlled_stock_ml` on every entry. Reconciliation independently recomputes the expected remainder from scratch: starting from the vehicle's controlled stock snapshot taken at lock, it replays every controlled-med entry whose appointment was serviced on this route, in `created_at` ascending order with ties broken by `created_at` and never by `id`, subtracting each entry's `amount_ml` — both `DISPENSE` and `WASTE` remove drug from the van. The expected remainder is that snapshot minus the summed consumption, taken to one decimal place with round-half-up, and this figure is stored as the vehicle's `controlled_reconciled_ml`. Reconciliation passes only if this independent recount equals the running `controlled_stock_ml` balance the day's side effects produced; if the two disagree, reconciliation is refused with `ERR_CONTROLLED_COUNT_MISMATCH`. The arithmetic of the euthanasia entries serviced on the route must square against the vehicle's stock movement for the same reason. A successful reconciliation recomputes `controlled_reconciled_ml`, returns the vehicle from `DEPLOYED` to `IN_DEPOT`, and returns the clinician from `ON_ROUTE` to `AVAILABLE`.

### 3.8. Specimens, Wellness Reminders, and the Recurring Cycle

Visits often collect samples for the lab. A `Clinician` records a **SpecimenPickup** against the visit's `appointment_id`, naming a `specimen_type` of `BLOOD`, `URINE`, or `TISSUE`; it begins in `COLLECTED` status. The clinician then moves it to `IN_TRANSIT` and finally to the terminal `DELIVERED` status, each step requiring the specimen to be in the immediately preceding state.

For ongoing care, a `Dispatcher` enrolls a patient in a **WellnessPlan** that drives recurring reminders. The plan names the `patient_id`, an `interval_days` cadence of at least 1 day, and an `anchor_date` from which the cycle is measured. From these the system computes `next_reminder_date`: starting at the anchor date, it steps forward by whole `interval_days` increments until the result lands strictly after the current clock. The comparison is strict — if a candidate date falls exactly on the current clock instant, that instant does not count as being in the future, so the system advances one more interval. As a consequence, a freshly created plan whose anchor lies in the future has a `next_reminder_date` equal to its `anchor_date`. The plan begins `ACTIVE`. A dispatcher may pause it from `ACTIVE` to `PAUSED` and resume it from `PAUSED` back to `ACTIVE`; resuming recomputes `next_reminder_date` against the current clock by the same forward-stepping rule. A plan may be ended from either `ACTIVE` or `PAUSED`, reaching the terminal `ENDED` status.

### 3.9. The DEA Audit Trail

The controlled-substance record is queryable for oversight. A `ComplianceOfficer` or a `Dispatcher` may pull the full `ControlledMedLog` history for a particular vehicle, or the subset of entries in which a particular clinician acted as the administering or witnessing vet, supporting per-vehicle and per-vet DEA audits. The entries for a single appointment may also be listed by a clinician, a compliance officer, or a dispatcher. Because every entry is immutable and timestamped at `created_at`, the trail is a faithful, append-only history of every controlled-drug movement.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource — including state transitions and the administrative clock and read operations — return `200 OK`. The request and response payloads for each operation are not restated here; they are reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-areas` | Create a ServiceArea (ZIP coverage) | Dispatcher |
| GET | `/service-areas` | List ServiceAreas; filter by `zip_code` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/service-areas/{id}` | Get a ServiceArea | Dispatcher, Clinician, ComplianceOfficer |
| POST | `/service-areas/{id}/suspend` | Suspend a ServiceArea | Dispatcher |
| POST | `/clinicians` | Register a Clinician (VET or TECH) | Dispatcher |
| GET | `/clinicians` | List Clinicians; filter by `clinician_role` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/clinicians/{id}` | Get a Clinician | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/clinicians/{id}/controlled-logs` | List controlled-med entries by acting vet (DEA audit) | ComplianceOfficer, Dispatcher |
| POST | `/rolling-clinics` | Create a RollingClinic with starting inventory | Dispatcher |
| GET | `/rolling-clinics` | List RollingClinics | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/rolling-clinics/{id}` | Get a RollingClinic | Dispatcher, Clinician, ComplianceOfficer |
| PATCH | `/rolling-clinics/{id}` | Set the vehicle maintenance flag | Dispatcher |
| GET | `/rolling-clinics/{id}/controlled-logs` | List controlled-med entries for a vehicle (DEA audit) | ComplianceOfficer, Dispatcher |
| POST | `/patients` | Create a Patient | Dispatcher |
| GET | `/patients/{id}` | Get a Patient | Dispatcher, Clinician, ComplianceOfficer |
| POST | `/appointments` | Create an Appointment (visit request) | Dispatcher |
| GET | `/appointments` | List Appointments; filter by `patient_id` or `service_area_id` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/appointments/{id}` | Get an Appointment | Dispatcher, Clinician, ComplianceOfficer |
| POST | `/appointments/{id}/arrive` | Clinician arrives on site | Clinician |
| POST | `/appointments/{id}/complete-visit` | Close the visit; finalize invoice | Clinician |
| POST | `/appointments/{id}/refer` | Refer the case to a hospital | Clinician |
| POST | `/appointments/{id}/cancel` | Cancel an appointment | Dispatcher |
| POST | `/appointments/{id}/euthanasia-log` | Append a controlled-med DISPENSE or WASTE entry | Clinician |
| GET | `/appointments/{id}/euthanasia-log` | List controlled-med entries for an appointment | Clinician, ComplianceOfficer, Dispatcher |
| POST | `/route-days` | Create a RouteDay | Dispatcher |
| GET | `/route-days` | List RouteDays; filter by `clinician_id` or `rolling_clinic_id` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/route-days/{id}` | Get a RouteDay | Dispatcher, Clinician, ComplianceOfficer |
| POST | `/route-days/{routeDayId}/stops` | Book an appointment as a RouteStop | Dispatcher |
| GET | `/route-days/{routeDayId}/stops` | List RouteStops on a RouteDay | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/route-stops` | List RouteStops; filter by `appointment_id` or `route_day_id` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/route-stops/{id}` | Get a RouteStop | Dispatcher, Clinician, ComplianceOfficer |
| POST | `/route-days/{id}/lock` | Lock the route day; deploy vehicle | Dispatcher |
| POST | `/route-days/{id}/reconcile` | Reconcile controlled stock and close the route | ComplianceOfficer |
| POST | `/estimates` | Create a DRAFT Estimate | Clinician |
| GET | `/estimates` | List Estimates; filter by `appointment_id` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/estimates/{id}` | Get an Estimate | Dispatcher, Clinician, ComplianceOfficer |
| PUT | `/estimates/{id}` | Revise DRAFT estimate line items | Clinician |
| POST | `/estimates/{id}/approve` | Approve a DRAFT estimate | Clinician |
| POST | `/payments` | Capture on-site payment | Clinician |
| GET | `/payments` | List Payments; filter by `estimate_id` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/payments/{id}` | Get a Payment | Dispatcher, Clinician, ComplianceOfficer |
| POST | `/specimen-pickups` | Record a collected specimen | Clinician |
| GET | `/specimen-pickups` | List SpecimenPickups; filter by `appointment_id` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/specimen-pickups/{id}` | Get a SpecimenPickup | Dispatcher, Clinician, ComplianceOfficer |
| POST | `/specimen-pickups/{id}/transit` | Mark specimen IN_TRANSIT | Clinician |
| POST | `/specimen-pickups/{id}/deliver` | Mark specimen DELIVERED | Clinician |
| POST | `/wellness-plans` | Enroll a patient in a wellness plan | Dispatcher |
| GET | `/wellness-plans` | List WellnessPlans; filter by `patient_id` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/wellness-plans/{id}` | Get a WellnessPlan | Dispatcher, Clinician, ComplianceOfficer |
| POST | `/wellness-plans/{id}/pause` | Pause a wellness plan | Dispatcher |
| POST | `/wellness-plans/{id}/resume` | Resume a paused plan | Dispatcher |
| POST | `/wellness-plans/{id}/end` | End a wellness plan | Dispatcher |
| GET | `/referrals` | List Referrals; filter by `appointment_id` | Dispatcher, Clinician, ComplianceOfficer |
| GET | `/referrals/{id}` | Get a Referral | Dispatcher, Clinician, ComplianceOfficer |
| POST | `/referrals/{id}/acknowledge` | Acknowledge a referral | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock | Dispatcher, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ROUTE_NOT_OPEN` | 409 Conflict |
| `ERR_ROUTE_EMPTY` | 409 Conflict |
| `ERR_STOPS_OPEN` | 409 Conflict |
| `ERR_AREA_NOT_COVERED` | 409 Conflict |
| `ERR_EUTHANASIA_NOT_PERMITTED` | 403 Forbidden |
| `ERR_EUTHANASIA_NOT_REFERABLE` | 409 Conflict |
| `ERR_VET_REQUIRED` | 403 Forbidden |
| `ERR_DEA_INVALID` | 403 Forbidden |
| `ERR_WITNESS_CONFLICT` | 403 Forbidden |
| `ERR_DOSE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_EUTHANASIA_LOG_INCOMPLETE` | 409 Conflict |
| `ERR_NO_APPROVED_ESTIMATE` | 409 Conflict |
| `ERR_APPT_NOT_IN_VISIT_PHASE` | 409 Conflict |
| `ERR_STOP_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_VEHICLE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_VEHICLE_UNAVAILABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_CONTROLLED_COUNT_MISMATCH` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_ROUTE_DAY_VERSION` | 412 Precondition Failed |
