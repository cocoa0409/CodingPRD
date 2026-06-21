# Blood Donation Center API — Product Requirements Document

## 1. Introduction

This document specifies the Blood Donation Center API, a system that governs the full chain of custody of donated blood — from the moment a donor walks in to register, through eligibility screening and deferral, appointment scheduling, the physical collection event, infectious-disease testing, unit labeling, inventory management, and finally the release or recall of finished blood products. The domain is unforgiving: a single missed deferral, an overlooked inter-donation interval, or an un-recalled unit can place a transfusion recipient at risk. The API therefore treats every clinical and regulatory rule as a hard gate rather than a guideline.

A defining characteristic of this system is that **time is deterministic**. Each donation center carries its own logical clock, and every interval calculation, deferral expiry, and shelf-life decision reads that clock rather than the server's wall clock. This makes the entire system reproducible and auditable: advancing a center's clock is an explicit, privileged action that also sweeps for newly-expired deferrals and newly-expired units. The reader should keep this in mind throughout — phrases like "now" or "the current time" always mean the center's own `current_utc`.

The remainder of this document is organized into global, system-wide specifications (Section 2), the detailed business logic and lifecycle workflows that distinguish this domain (Section 3), a consolidated endpoint table (Section 4), and the error code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes five roles, spelled exactly as follows: `CenterAdmin`, `IntakeNurse`, `LabTechnician`, `InventoryManager`, and `Donor`. A `CenterAdmin` manages donation centers, the deterministic clock, and appointment slots, and holds read access across the center. An `IntakeNurse` registers donors, runs health screenings, raises and lifts deferrals, checks donors in, records collections, and logs adverse reactions. A `LabTechnician` records infectious-disease test results, labels blood units, and logs adverse reactions. An `InventoryManager` drives the blood-unit lifecycle (reserve, unreserve, issue), initializes inventory buckets, and opens recall/lookback events. A `Donor` is a self-service participant who registers, books and cancels their own appointments, and reads their own records.

Four of these roles are operator roles whose identity is opaque. When `X-User-Role` is `CenterAdmin`, `IntakeNurse`, `LabTechnician`, or `InventoryManager`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. The `Donor` role, by contrast, is entity-backed: when `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting `Donor` record. The server records this `X-User-ID` but does not enforce any ownership comparison: a request authorized by role alone is accepted regardless of whether the `X-User-ID` matches the `donor_id` (or any other donor foreign key) named in the request or carried by the target resource. In other words, a `Donor`-role caller may book, cancel, or read records that reference a different `Donor`, and no ownership-based rejection is raised on that basis; only the role gate of §2.6 (priority 2) governs access.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0. A `limit` outside the 1–100 range, an `offset` below 0, or a `limit`/`offset` that is not a parseable integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response includes the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Deterministic Center Clock

Every primary resource in this system carries a system-managed `id`, formatted as a UUID with no type prefix, assigned by the server at creation and immutable thereafter. Each resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the row was first created. All entities in this domain additionally maintain an `updated_at` timestamp (same format), refreshed on every mutation, and a `version`, an integer that begins at its initial value and increments by one on every mutation of the resource. There are no immutable-after-creation entities here; all carry the full quartet of `id`, `created_at`, `updated_at`, and `version`.

The center clock deserves special emphasis. A `DonationCenter` carries a `current_utc` field that represents the center's logical "now." It is initialized to `1970-01-01T00:00:00.000Z` at center creation and only ever moves forward through the dedicated clock-advance capability. Every time-sensitive computation in the system — inter-donation intervals, deferral expiry, unit shelf life, recall lookback windows, and donor age — is evaluated against this `current_utc`, never against real-world time. Reading a center returns its `current_utc` and `version`.

### 2.5. Reverse Reachability and Resource Existence

This API uses a flat topology: every entity is a peer top-level collection mounted under `/blood-bank`, and entities are linked by foreign-key fields carried in request bodies rather than by nested URL paths. Navigation from a parent to its children is therefore performed through filtered list endpoints — for example, listing donations filtered by a `donor_id`, or listing blood units filtered by a `donation_id`. Each list endpoint that supports such filtering accepts the relevant foreign-key field as a query parameter.

For any request that names resource identifiers — whether a path identifier such as `{donorId}` or a body foreign key such as `donor_id` or `slot_id` — the system validates existence before applying business rules. Path identifiers are validated left-to-right, and body foreign keys are then validated in their declared order. The first identifier that does not resolve to an existing resource causes the request to be rejected with the matching not-found error (`ERR_NOT_FOUND` generically, or the resource-specific variant such as `ERR_CENTER_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`, `ERR_DEFERRAL_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_TEST_RESULT_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_REACTION_NOT_FOUND`, `ERR_RECALL_EVENT_NOT_FOUND`, or `ERR_BUCKET_NOT_FOUND`), all returned with HTTP 404.

### 2.6. Request Validation and the Order of Checks

Every mutation request is screened in a fixed priority order, and the first failing check determines the response. Authentication and authorization come first: header validity (priority 1, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role permission (priority 2, `ERR_INSUFFICIENT_PERMISSIONS`). Existence of all referenced resources is checked next (priority 3, the 404 family described in §2.5). Then comes basic request well-formedness (priority 4): all required fields must be present, enum-typed fields must carry a recognized value, numeric fields must lie in their permitted range, and datetime fields must be valid ISO 8601 — any violation yields `ERR_INVALID_REQUEST` with HTTP 400.

Only after these four universal gates pass does the system evaluate domain-specific checks. For booking, the optimistic-concurrency check (priority 5) runs before any slot capacity or slot-state business check. State-eligibility of the target resource (priority 6) is then verified, followed by the various business-safety, business-temporal, and business-constraint rules that are detailed in their respective workflows in Section 3. Where a single endpoint carries several domain checks, the relative ordering is called out in the workflow narrative so that the first applicable rejection is deterministic.

### 2.7. Optimistic Concurrency Control on Slot Booking

Booking an appointment is the one operation in this system protected by optimistic concurrency control. Because many donors compete for a limited number of seats in an `AppointmentSlot`, the booking request must carry an `expected_slot_version` field whose value is the `version` of the target slot as the client last observed it. This field is mandatory for booking. If a writer has already booked the slot since the client last read it — legitimately bumping the slot's `booked_count` and advancing its `version` — then the client's view of remaining capacity is stale, and the `expected_slot_version` will no longer match the slot's current `version`. In that case the booking is rejected with `ERR_STALE_SLOT_VERSION` at HTTP 412, before any capacity or slot-state check runs, so the client is forced to re-read the slot before retrying. This rejection is framed entirely in terms of stale versions, not in terms of requests arriving at the same instant. No other endpoint in the system takes a version field, and none performs an OCC check.

### 2.8. Hierarchical Cascades and Derived-Field Reconciliation

Many operations in this system mutate more than one entity. The system applies these cascades synchronously and in full: a single collection event, test result, adverse reaction, recall, or clock advance can ripple across donors, donations, units, deferrals, and inventory buckets. Each entity touched by a cascade has its own `updated_at` refreshed and its `version` incremented, exactly as if it had been mutated directly. The detailed cascades are specified in Section 3, but two derived-field families warrant a system-wide statement here.

First, donor status fields are **derived, not free-standing**. A donor's `eligibility_status` is recomputed from their active deferrals and their age relative to `current_utc` whenever a deferral is created, expires, or is lifted, and on every clock advance. Likewise `last_qualifying_donation_id`, `pending_donation_type`, and `lifetime_collected_count` are recomputed as donations and appointments change state. Reading a donor recomputes `eligibility_status` and the interval fields against the current clock before responding.

Second, inventory bucket counts are derived. For each `(blood_type, component)` bucket at a center, `available_count` equals the number of that center's blood units in `AVAILABLE` status with that blood type and component, and `reserved_count` equals the number in `RESERVED` status. These counts are maintained incrementally by the unit state-machine side effects, but they are an invariant: at every moment the stored counts must equal a fresh recount over the underlying unit rows. Both the list and single-bucket read endpoints reflect this live recount.

### 2.9. Datetime, Volume, and Precision Conventions

All datetime arithmetic in this system is performed in whole seconds, using the conversion factor of 86,400 seconds per day; no rounding of dates is performed. Interval and shelf-life computations add a whole number of days (converted to seconds) to an anchor timestamp and compare the result against `current_utc`. Boundary comparisons are inclusive where the rule says "at least" or "on or after" and exclusive where the rule says "strictly after"; the precise direction for each rule is stated in Section 3.

The one place where decimal rounding matters is the rolling annual plasma volume, which is expressed in liters to two decimal places using the round-half-up method, with the rounding applied per collection before summation (detailed in §3.5). Hemoglobin is compared at one decimal place. All other measured quantities — volumes in milliliters, weights in kilograms, blood pressure, and pulse — are taken at their input precision.

## 3. Business Logic & Workflows

### 3.1. Centers, the Clock, and the Scheduled Sweeps

Everything begins with a `DonationCenter`, created by a `CenterAdmin` with a `name` and a `region_code` (for example, `US-CA`). At creation the center's `current_utc` is set to `1970-01-01T00:00:00.000Z`. Centers can be listed (optionally filtered by `region_code`) and read individually by any role.

Advancing the clock is a `CenterAdmin` capability that supplies a target instant as `to_iso8601`. The target must be strictly after the center's existing `current_utc`; an equal or earlier target is rejected with `ERR_CLOCK_NOT_MONOTONIC`. When the clock advances, the new value is written to `current_utc` and two deterministic sweeps run. The first sweep examines every `ACTIVE` deferral that is `TEMPORARY`: any whose `expires_at` is at or before the new `current_utc` transitions from `ACTIVE` to `EXPIRED`, and the affected donor's `eligibility_status` is recomputed. The second sweep examines every `AVAILABLE` blood unit: any whose `expires_at` is at or before the new `current_utc` transitions from `AVAILABLE` to `EXPIRED`, and the matching inventory bucket's `available_count` is decremented by one for each such unit. The clock advance returns the updated center.

### 3.2. Donor Registration, Eligibility, and Deferrals

A donor is registered — by an `IntakeNurse` or by a self-service `Donor` — against a center via `center_id`, supplying a `full_name`, a `date_of_birth` (an ISO date in `YYYY-MM-DD` form), a self-reported `weight_kg`, and a `blood_type`. The blood type is one of `O_NEG`, `O_POS`, `A_NEG`, `A_POS`, `B_NEG`, `B_POS`, `AB_NEG`, `AB_POS`, or `UNKNOWN`. At registration the system computes `eligibility_status`: if the donor's age at the center's `current_utc` is less than 18 years, the status is `UNDERAGE`; otherwise it is `ELIGIBLE`. The donor's `lifetime_collected_count` starts at 0 and `pending_donation_type` starts at `NONE`.

A donor's `eligibility_status` is one of `ELIGIBLE`, `TEMP_DEFERRED`, `PERM_DEFERRED`, or `UNDERAGE`. It is derived from the donor's active deferrals together with their age: a donor with any `ACTIVE` `PERMANENT` deferral is `PERM_DEFERRED`; a donor with at least one `ACTIVE` `TEMPORARY` deferral (and no permanent one) is `TEMP_DEFERRED`; a donor under 18 with no active deferral is `UNDERAGE`; and a donor of age with no active deferral is `ELIGIBLE`. This status is recomputed on every deferral create, expire, or lift, and on every clock advance.

A **deferral** records a clinical reason a donor may not give blood. An `IntakeNurse` raises one against a donor by supplying `donor_id`, a `category`, a `kind`, and a free-text `reason` of at least 5 characters. The `category` is one of `TRAVEL`, `MEDICATION`, `HEMOGLOBIN`, `ADVERSE_REACTION`, or `INFECTIOUS_RISK`. The `kind` is either `TEMPORARY` or `PERMANENT`. A temporary deferral must carry a `duration_days` that is an integer of at least 1; a permanent deferral must not carry `duration_days` at all. Violating this — a temporary deferral with a missing or sub-1 `duration_days`, or a permanent deferral that includes `duration_days` — is rejected with `ERR_INVALID_DEFERRAL_DURATION` at HTTP 422. On creation the deferral's `center_id` is copied from the donor, its `starts_at` is set to the center's `current_utc`, and its `status` defaults to `ACTIVE`. For a temporary deferral, `expires_at` is computed as `starts_at` plus `duration_days` days (each day being 86,400 seconds); for a permanent deferral, `expires_at` is null. A deferral may also carry a `source_reaction_id` linking it back to the adverse reaction that raised it (set automatically in the reaction cascade described in §3.6). Raising a deferral recomputes the donor's `eligibility_status` to `TEMP_DEFERRED` or `PERM_DEFERRED` as appropriate.

A deferral's `status` is one of `ACTIVE`, `EXPIRED`, or `LIFTED`. A temporary deferral expires automatically — moving from `ACTIVE` to `EXPIRED` — during a clock-advance sweep once the center's `current_utc` reaches or passes its `expires_at`; a permanent deferral never expires on its own and remains `ACTIVE` until lifted. An `IntakeNurse` may lift an active deferral, transitioning it from `ACTIVE` to `LIFTED`. The two lift preconditions are evaluated in this order: first, the deferral must be `ACTIVE`, otherwise `ERR_DEFERRAL_NOT_ACTIVE` is returned; then, a deferral whose `category` is `INFECTIOUS_RISK` can never be lifted and such an attempt is rejected with `ERR_INFECTIOUS_DEFERRAL_NOT_LIFTABLE`. Because the `ACTIVE` check runs first, an attempt to lift an `INFECTIOUS_RISK` deferral that is already `EXPIRED` or `LIFTED` yields `ERR_DEFERRAL_NOT_ACTIVE`, not `ERR_INFECTIOUS_DEFERRAL_NOT_LIFTABLE`. When the precondition holds, the lift sets the status to `LIFTED` and recomputes the donor's `eligibility_status`. Deferrals can be listed with filters on `donor_id`, `center_id`, `source_reaction_id`, `status`, and `category`, and read individually.

### 3.3. Slots, Booking, and the Single-Appointment Rule

A `CenterAdmin` creates an `AppointmentSlot` for a center with a `center_id`, a `donation_type` (one of `WHOLE`, `PLASMA`, or `PLATELET` — the only donation type bookable in that slot), a `starts_at`, an `ends_at`, and a `capacity` that is an integer of at least 1. The window must be valid: `ends_at` must be strictly after `starts_at`, otherwise `ERR_INVALID_SLOT_WINDOW` (HTTP 422) is returned. A new slot has `booked_count` of 0 and `status` of `OPEN`. A slot's `status` is one of `OPEN`, `FULL`, or `CLOSED`: it becomes `FULL` automatically when `booked_count` reaches or exceeds `capacity`, and a `CenterAdmin` may explicitly close a slot, setting `status` to `CLOSED`. Slots can be listed (filtered by `center_id`, `donation_type`, or `status`) and read individually, where the response exposes `booked_count`, `status`, and `version`.

Booking an **appointment** ties a donor to a slot. A `Donor` (booking for themselves) or an `IntakeNurse` submits a `donor_id`, a `slot_id`, and the `expected_slot_version` required by the optimistic-concurrency rule of §2.7. After the OCC check passes, the system enforces two business constraints. The slot must be bookable: a slot that is `CLOSED` or `FULL` is rejected with `ERR_SLOT_NOT_BOOKABLE`. And the donor may hold at most one open appointment — that is, at most one appointment in `SCHEDULED` or `CHECKED_IN` status — at a time; a second concurrent open appointment is rejected with `ERR_DONOR_HAS_OPEN_APPOINTMENT`. When booking succeeds, the appointment's `center_id` and `donation_type` are copied from the slot, its `status` is set to `SCHEDULED`, and its `booked_at` is set to the center's `current_utc`. The slot's `booked_count` is incremented by one, its `version` is incremented by one, and its `status` flips to `FULL` if `booked_count` now reaches or exceeds `capacity`. The donor's `pending_donation_type` is recomputed to reflect the new open appointment.

An appointment's `status` follows the path `SCHEDULED` → `CHECKED_IN` → `COMPLETED` or `NO_SHOW`, with `SCHEDULED` → `CANCELLED` as the early-exit branch; `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal. Appointments can be listed (filtered by `donor_id`, `slot_id`, `center_id`, or `status`) and read individually. A donor's `pending_donation_type` mirrors the donation type of their single open appointment and is `NONE` when they have none; its possible values are `WHOLE`, `PLASMA`, `PLATELET`, and `NONE`.

A scheduled appointment may be **cancelled** by the owning `Donor` or by an `IntakeNurse`. Cancellation requires the appointment to be `SCHEDULED`; otherwise `ERR_APPOINTMENT_NOT_CANCELLABLE` is returned. On cancel, the appointment moves to `CANCELLED`, the slot's `booked_count` is decremented by one and its `status` is recomputed (a slot that was `FULL` returns to `OPEN` once it falls below capacity), and the donor's `pending_donation_type` is recomputed back to `NONE` if this was their open appointment.

### 3.4. Screening and Check-In

Before a checked-in donor can give blood, an `IntakeNurse` records a **health screening** for the appointment. Recording a screening imposes no appointment-state precondition — the referenced `appointment_id` need only resolve to an existing appointment, and a screening may be recorded against an appointment in any status. The screening references the appointment through `appointment_id` (its `donor_id` is copied from that appointment) and captures the measured `hemoglobin_g_dl`, `systolic_bp`, `pulse_bpm`, and `weight_kg`, plus two questionnaire flags: `recent_travel_risk` (true when travel history flags an endemic-risk region) and `disqualifying_medication` (true when a listed disqualifying medication is reported). The system computes an `outcome` of `PASS` or `FAIL` and, on failure, a `failure_reason`.

The screening evaluates five checks in this fixed order, and the **first** check that fails sets both `outcome` to `FAIL` and the `failure_reason`; only if all five pass is the outcome `PASS`. First, hemoglobin: it passes only when `hemoglobin_g_dl` is at least 12.5 g/dL (the input is first rounded to one decimal place using round-half-up and then compared, so exactly 12.5 passes); below that, the reason is `HEMOGLOBIN_LOW`. Second, weight: `weight_kg` must be at least 50 kg, else `UNDERWEIGHT`. Third, vitals: `systolic_bp` must lie between 90 and 180 inclusive and `pulse_bpm` must lie between 50 and 100 inclusive — if either falls outside its range, the reason is `VITALS_OUT_OF_RANGE`. Fourth, travel: `recent_travel_risk` must be false, else `TRAVEL_RISK`. Fifth, medication: `disqualifying_medication` must be false, else `MEDICATION`. When all pass, `failure_reason` is `NONE`. The possible `failure_reason` values are therefore `NONE`, `HEMOGLOBIN_LOW`, `UNDERWEIGHT`, `VITALS_OUT_OF_RANGE`, `TRAVEL_RISK`, and `MEDICATION`.

A failing screening has a conditional side effect: when the `failure_reason` is one of `HEMOGLOBIN_LOW`, `TRAVEL_RISK`, or `MEDICATION`, the system automatically raises a `TEMPORARY` deferral against the donor and recomputes their `eligibility_status` to `TEMP_DEFERRED`. The category and duration follow the reason: a `HEMOGLOBIN_LOW` failure raises a `HEMOGLOBIN` deferral lasting 90 days, a `TRAVEL_RISK` failure raises a `TRAVEL` deferral lasting 21 days, and a `MEDICATION` failure raises a `MEDICATION` deferral lasting 14 days. The other two failure reasons — `UNDERWEIGHT` and `VITALS_OUT_OF_RANGE` — fail the screening but do not auto-defer the donor. Screenings can be listed (filtered by `appointment_id`, `donor_id`, or `outcome`) and read individually.

Checking a donor in is an `IntakeNurse` action that advances the appointment from `SCHEDULED` to `CHECKED_IN`. It is gated by three preconditions evaluated in order. The appointment must be `SCHEDULED`, else `ERR_APPOINTMENT_NOT_SCHEDULED`. The donor's `eligibility_status` must equal `ELIGIBLE` at the center's `current_utc`, else `ERR_DONOR_NOT_ELIGIBLE` (HTTP 403). And the inter-donation interval for the slot's donation type must have elapsed, else `ERR_INTERVAL_NOT_ELAPSED` — this is the authoritative interval gate described in §3.5.

### 3.5. Inter-Donation Intervals and Plasma Volume Caps

The system enforces a minimum number of days between collections, which varies by donation type: 56 days for `WHOLE`, 28 days for `PLASMA`, and 7 days for `PLATELET`. The interval is evaluated in two variants that must not be conflated.

The **FINAL** variant is authoritative and is the one enforced at check-in. Its base is the `collected_at` of the donation pointed to by the donor's `last_qualifying_donation_id` — that is, the donor's most recent donation that reached `COLLECTED` or beyond, ranked by `collected_at` descending and then `created_at` descending. The donor's next eligible instant is that base plus the interval for the slot's donation type (the appropriate number of days converted at 86,400 seconds per day). The interval is satisfied when the center's `current_utc` is at or after that next eligible instant; a donation exactly the interval's number of days later is therefore eligible. If the donor has no qualifying donation, the base is the epoch (`1970-01-01T00:00:00.000Z`), so the interval is always already elapsed. This FINAL variant considers only the actual last qualifying collection and ignores any open appointment.

The **PROVISIONAL** variant is a booking advisory only and never blocks booking. It is the more conservative of two candidate bases: the `collected_at` of the donor's most recent `COLLECTED`-or-beyond donation of the requested type, and the implied date of the donor's open appointment when their `pending_donation_type` equals the requested type. The later of those two anchors is used, yielding a later — more cautious — eligible date that advises the donor a slot may be too soon. Enforcement at check-in always uses FINAL.

**Plasma volume caps.** Recording a collection for a `PLASMA` donation is subject to two independent ceilings, and the order of operations is deliberately pinned because it changes the outcome. First, a per-collection cap by weight band, where the governing weight is the measured `weight_kg` from the appointment's passing screening (falling back to the donor's registered `weight_kg` if that is absent): a weight of at least 50 kg and below 68 kg caps the collection at 690 mL; at least 68 kg and below 79 kg caps it at 825 mL; at least 79 kg caps it at 880 mL; and a governing weight below 50 kg falls back to the lowest band cap of 690 mL (this band is normally unreachable because underweight is screened out earlier). The collection's `volume_ml` must not exceed the applicable band cap, otherwise `ERR_PLASMA_VOLUME_EXCEEDED` (HTTP 422) is returned.

Second, a rolling 365-day plasma-volume ceiling. The system gathers each of the donor's prior `PLASMA` donations whose `collected_at` falls within the trailing 365 days (those with status `COLLECTED` or `RELEASABLE`) together with the in-flight collection. For each of these, it converts that collection's volume in milliliters to liters by dividing by 1000 and **rounding that single line to two decimal places using round-half-up first**, then sums the already-rounded per-collection liter figures to get the annual total. If that annual total is greater than 2.00 liters the collection is rejected with `ERR_ANNUAL_PLASMA_CAP_EXCEEDED` (HTTP 422); a total of exactly 2.00 liters is allowed, and 2.01 is rejected. The round-then-sum order is mandatory: three collections of 666 mL each round to 0.67 L per line and sum to 2.01 L (rejected), whereas summing first would give 1.998 L rounding to 2.00 L — the per-line rounding is authoritative, so such a case rejects. Each prior collection may be individually valid while the rolling sum tips over the ceiling.

### 3.6. The Collection Event, Testing, and Adverse Reactions

Recording a collection is the clinical heart of the workflow and is performed by an `IntakeNurse` for a checked-in appointment, supplying the collected `volume_ml` (an integer of at least 1). This single action completes the appointment and creates a donation. Its preconditions are evaluated in order: the appointment must be `CHECKED_IN`, else `ERR_APPOINTMENT_NOT_CHECKED_IN`; a health screening with `outcome` of `PASS` must exist for the appointment, else `ERR_SCREENING_NOT_PASSED`; and for a `PLASMA` donation the two plasma caps of §3.5 are enforced (the per-collection band cap first, yielding `ERR_PLASMA_VOLUME_EXCEEDED`, then the rolling annual cap, yielding `ERR_ANNUAL_PLASMA_CAP_EXCEEDED`).

When collection succeeds, several things happen together. The appointment transitions from `CHECKED_IN` to `COMPLETED`. A `Donation` row is created in `COLLECTED` status with its `appointment_id` recorded and its `donor_id`, `center_id`, and `donation_type` copied from the appointment, and its `collected_at` set to the center's `current_utc`. Because the appointment has left the open set, the slot's `booked_count` is decremented by one and its `status` is recomputed. On the donor, `lifetime_collected_count` is incremented by one, `last_qualifying_donation_id` is recomputed, and the eligibility and interval fields are recomputed. A donation's `status` is `COLLECTED` initially and forks to either `RELEASABLE` or `DISCARDED`; it also carries a convenience `test_result_id` pointer that is null until a result is recorded. Donations can be listed (filtered by `donor_id`, `appointment_id`, `center_id`, `status`, or `donation_type`) and read individually.

Marking a checked-in donor as a **no-show** is an `IntakeNurse` action available only after the slot window has ended — that is, the center's `current_utc` must be at or after the slot's `ends_at`, else `ERR_SLOT_WINDOW_OPEN`. It also requires the appointment to be `CHECKED_IN`, else `ERR_APPOINTMENT_NOT_CHECKED_IN`. A no-show transitions the appointment from `CHECKED_IN` to `NO_SHOW`, decrements the slot's `booked_count` and recomputes its `status`, and recomputes the donor's `pending_donation_type` to `NONE`.

**Testing.** A `LabTechnician` records the infectious-disease panel result for a donation, supplying a `panel_outcome` of `NEGATIVE`, `POSITIVE`, or `INDETERMINATE`. This creates a `TestResult` (referencing the donation through `donation_id`, copying `donor_id` from it, and stamping `resulted_at` with the center's `current_utc`) and sets the donation's `test_result_id`. The donation must be in `COLLECTED` status, else `ERR_DONATION_NOT_COLLECTED`. On a `NEGATIVE` result, releasing additionally requires that no `SEVERE` adverse reaction exists for the donation; if one does, the release is blocked with `ERR_SEVERE_REACTION_BLOCKS_RELEASE`. When the panel is `NEGATIVE` and no severe reaction blocks it, the donation transitions from `COLLECTED` to `RELEASABLE`, and every `QUARANTINED` blood unit of that donation is released to `AVAILABLE` (with `released_at` set to `current_utc`, platelet expiry recomputed on a release-anchored basis per §3.7, and the matching inventory bucket's `available_count` incremented by one per released unit). When the panel is `POSITIVE` or `INDETERMINATE`, the donation transitions from `COLLECTED` to `DISCARDED`, and every `QUARANTINED` blood unit of that donation is discarded (moving to `DISCARDED` with no inventory change, as those units were never `AVAILABLE`). A `POSITIVE` result has one further cascade: a `PERMANENT` deferral of category `INFECTIOUS_RISK` is auto-raised for the donor, driving their `eligibility_status` to `PERM_DEFERRED`. Test results can be listed (filtered by `donation_id`, `donor_id`, or `panel_outcome`) and read individually.

**Adverse reactions.** An `IntakeNurse` or `LabTechnician` logs an adverse reaction against a donation, supplying `donation_id`, a `severity` of `MILD`, `MODERATE`, or `SEVERE`, and a `symptom` description of at least 3 characters. The reaction copies `donor_id` from the donation and stamps `occurred_at` with the center's `current_utc`. When the severity is `SEVERE`, the system auto-raises a `PERMANENT` deferral of category `ADVERSE_REACTION` for the donor, sets that deferral's `source_reaction_id` to this reaction, records the new deferral's id on the reaction's `triggered_deferral_id`, and drives the donor's `eligibility_status` to `PERM_DEFERRED`; for `MILD` or `MODERATE` reactions the `triggered_deferral_id` stays null. A standing severe reaction is also what blocks a later release of the donation's units. Adverse reactions can be listed (filtered by `donation_id`, `donor_id`, or `severity`) and read individually.

### 3.7. Unit Labeling, Shelf Life, and the Inventory Lifecycle

A `LabTechnician` labels a **blood unit** from a `COLLECTED` donation by supplying `donation_id`, a `component`, and a `din` (the Donation Identification Number on the unit's label). The `component` is one of `RBC`, `PLASMA`, `PLATELET`, or `WHOLE_BLOOD`, and it must be compatible with the parent donation's `donation_type`: a `WHOLE` donation may yield `RBC`, `PLASMA`, or `WHOLE_BLOOD`; a `PLASMA` donation may yield only `PLASMA`; and a `PLATELET` donation may yield only `PLATELET`. An incompatible component is rejected with `ERR_COMPONENT_TYPE_MISMATCH` (HTTP 422). The `din` must be unique among all blood units at the center; a duplicate is rejected with `ERR_DUPLICATE_DIN`. On labeling, the unit copies `donor_id`, `center_id`, and `blood_type` (from the donor at labeling time), copies `collected_at` from the parent donation, computes its `expires_at` shelf life as described below, and starts in `QUARANTINED` status. Units can be listed (filtered by `donation_id`, `donor_id`, `center_id`, `blood_type`, `component`, or `status`) and read individually.

Shelf life uses two anchoring schemes by component. For `RBC`, `PLASMA`, and `WHOLE_BLOOD` the expiry is **collection-anchored** and fixed at labeling: `expires_at` is the `collected_at` plus the component's shelf life — 42 days for `RBC`, 365 days for `PLASMA`, and 35 days for `WHOLE_BLOOD` (each day being 86,400 seconds). For `PLATELET` the expiry is **release-anchored**: a platelet in quarantine has no started clock, and its `expires_at` is computed only when the unit becomes `AVAILABLE`, as the `released_at` instant plus 5 days, overwriting any prior value. A unit is expired when the center's `current_utc` is at or after its `expires_at`.

A blood unit's `status` begins at `QUARANTINED` and follows a branching machine. From `QUARANTINED` it can move (by system cascade) to `AVAILABLE` when its parent donation becomes releasable, to `DISCARDED` when its parent donation is discarded, or to `RECALLED` by a recall cascade (with no inventory change, since it was never available). From `AVAILABLE` it can move to `RESERVED` (by an `InventoryManager` reserving it), to `EXPIRED` (by the clock-advance sweep), or to `RECALLED` (by a recall cascade). From `RESERVED` it can move to `ISSUED`, back to `AVAILABLE` (unreserve), or to `RECALLED`. The states `DISCARDED`, `RECALLED`, `ISSUED`, and `EXPIRED` are terminal. The release-on-availability transition sets `released_at` to the center's `current_utc`, recomputes platelet expiry, and increments the matching bucket's `available_count`.

Reserving a unit is an `InventoryManager` action requiring the unit to be `AVAILABLE`, else `ERR_UNIT_NOT_AVAILABLE`, and requiring the center's `current_utc` to be strictly before the unit's `expires_at`, else `ERR_UNIT_EXPIRED`. A successful reservation moves the unit from `AVAILABLE` to `RESERVED`, decrements the bucket's `available_count` by one, and increments its `reserved_count` by one. Unreserving requires the unit to be `RESERVED`, else `ERR_UNIT_NOT_RESERVED`; it returns the unit to `AVAILABLE`, decrements `reserved_count` by one, and increments `available_count` by one. Issuing a unit to a hospital order also requires the unit to be `RESERVED`, else `ERR_UNIT_NOT_RESERVED`; it moves the unit to `ISSUED` and decrements `reserved_count` by one.

**Inventory buckets.** An `InventoryManager` initializes an `InventoryBucket` for a `(center_id, blood_type, component)` triple, where `blood_type` and `component` are the two parts of the bucket key. At creation the bucket's `available_count` and `reserved_count` are initialized from a recount of the center's existing units matching that key. Thereafter the counts are maintained by the unit-lifecycle side effects and always equal a live recount, as stated in §2.8. Buckets can be listed (filtered by `center_id`, `blood_type`, or `component`) and read individually; each read reflects the live recount.

### 3.8. Recall and Lookback

When post-donation information surfaces — a positive retest, a reported post-donation illness, a late travel disclosure, or other cause — an `InventoryManager` opens a **recall event** against a donor. The request supplies `center_id`, `donor_id`, a `reason` of `POSITIVE_RETEST`, `POST_DONATION_ILLNESS`, `TRAVEL_DISCLOSURE`, or `OTHER`, and a `lookback_days` window that is an integer of at least 1. The donor must exist, else `ERR_DONOR_NOT_FOUND`. The recall runs its cascade synchronously and then closes; its `status` moves from `OPEN` to `CLOSED` in a single operation.

The cascade proceeds in deterministic order. First, scope selection: the window start is the center's `current_utc` minus `lookback_days` days (converted at 86,400 seconds per day), and the donations in scope are the donor's donations whose `collected_at` is at or after that window start — a donation falling exactly on the window start is in scope. These are ordered by `collected_at` ascending and then `created_at` ascending for a deterministic cascade, and their count is recorded in `donations_in_scope_count`. Second, each in-scope donation that is not already `DISCARDED` is moved to `DISCARDED`. Third, each non-terminal blood unit of those donations — those in `QUARANTINED`, `AVAILABLE`, or `RESERVED` status — is transitioned to `RECALLED`; for each such unit that was `AVAILABLE` the matching bucket's `available_count` is decremented, and for each that was `RESERVED` the bucket's `reserved_count` is decremented (a `QUARANTINED` unit causes no inventory change), and `units_recalled_count` is incremented accordingly. Units already in a terminal state — `ISSUED`, `EXPIRED`, or already `DISCARDED` — are neither recalled nor counted. Fourth, if the `reason` is `POSITIVE_RETEST`, a `PERMANENT` deferral of category `INFECTIOUS_RISK` is auto-raised for the donor and their `eligibility_status` is driven to `PERM_DEFERRED`. Finally the recall event's `status` is set to `CLOSED`. Recall events can be listed (filtered by `center_id`, `donor_id`, or `status`) and read individually, exposing the resulting `donations_in_scope_count` and `units_recalled_count`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and the clock advance — return a `200 OK` status code. All list and single-resource read operations return `200 OK`. Refer back to Section 3 for the request payloads, preconditions, and side effects of each operation; the table below is intentionally limited to routing and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/blood-bank/centers` | Create a donation center | CenterAdmin |
| GET | `/blood-bank/centers` | List centers | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager, Donor |
| GET | `/blood-bank/centers/{centerId}` | Get a center (includes current_utc and version) | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager, Donor |
| POST | `/blood-bank/centers/{centerId}/clock/advance` | Advance the center clock; runs deferral- and unit-expiry sweeps | CenterAdmin |
| POST | `/blood-bank/donors` | Register a donor | IntakeNurse, Donor |
| GET | `/blood-bank/donors` | List donors, filterable by `center_id`, `eligibility_status`, and `blood_type` | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager |
| GET | `/blood-bank/donors/{donorId}` | Get a donor (eligibility/interval fields recomputed) | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager, Donor |
| POST | `/blood-bank/deferrals` | Raise a deferral against a donor | IntakeNurse |
| GET | `/blood-bank/deferrals` | List deferrals, filterable | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager, Donor |
| GET | `/blood-bank/deferrals/{deferralId}` | Get a deferral | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager, Donor |
| POST | `/blood-bank/deferrals/{deferralId}/lift` | Lift an active deferral (not for INFECTIOUS_RISK) | IntakeNurse |
| POST | `/blood-bank/slots` | Create an appointment slot | CenterAdmin |
| GET | `/blood-bank/slots` | List slots, filterable | CenterAdmin, IntakeNurse, InventoryManager, Donor |
| GET | `/blood-bank/slots/{slotId}` | Get a slot (booked_count, status, version) | CenterAdmin, IntakeNurse, InventoryManager, Donor |
| POST | `/blood-bank/slots/{slotId}/close` | Close a slot to new bookings | CenterAdmin |
| POST | `/blood-bank/appointments` | Book an appointment for a donor into a slot | Donor, IntakeNurse |
| GET | `/blood-bank/appointments` | List appointments, filterable | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager, Donor |
| GET | `/blood-bank/appointments/{appointmentId}` | Get an appointment | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager, Donor |
| POST | `/blood-bank/appointments/{appointmentId}/check-in` | Check a donor in | IntakeNurse |
| POST | `/blood-bank/appointments/{appointmentId}/cancel` | Cancel a scheduled appointment | Donor, IntakeNurse |
| POST | `/blood-bank/appointments/{appointmentId}/no-show` | Mark a checked-in donor as no-show after the slot window | IntakeNurse |
| POST | `/blood-bank/appointments/{appointmentId}/donations` | Record the collection event for a checked-in donor | IntakeNurse |
| POST | `/blood-bank/health-screenings` | Record a pre-donation health screening | IntakeNurse |
| GET | `/blood-bank/health-screenings` | List screenings, filterable | CenterAdmin, IntakeNurse, LabTechnician |
| GET | `/blood-bank/health-screenings/{screeningId}` | Get a screening | CenterAdmin, IntakeNurse, LabTechnician |
| GET | `/blood-bank/donations` | List donations, filterable | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager |
| GET | `/blood-bank/donations/{donationId}` | Get a donation | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager |
| POST | `/blood-bank/donations/{donationId}/test-results` | Record the infectious-disease panel result | LabTechnician |
| GET | `/blood-bank/test-results` | List test results, filterable | CenterAdmin, LabTechnician, InventoryManager |
| GET | `/blood-bank/test-results/{testResultId}` | Get a test result | CenterAdmin, LabTechnician, InventoryManager |
| POST | `/blood-bank/blood-units` | Label a blood unit from a COLLECTED donation | LabTechnician |
| GET | `/blood-bank/blood-units` | List units, filterable | CenterAdmin, LabTechnician, InventoryManager |
| GET | `/blood-bank/blood-units/{unitId}` | Get a unit (status, expires_at) | CenterAdmin, LabTechnician, InventoryManager |
| POST | `/blood-bank/blood-units/{unitId}/reserve` | Reserve an available, non-expired unit | InventoryManager |
| POST | `/blood-bank/blood-units/{unitId}/unreserve` | Release a reserved unit back to available | InventoryManager |
| POST | `/blood-bank/blood-units/{unitId}/issue` | Issue a reserved unit to a hospital order | InventoryManager |
| POST | `/blood-bank/adverse-reactions` | Log an adverse reaction against a donation | IntakeNurse, LabTechnician |
| GET | `/blood-bank/adverse-reactions` | List reactions, filterable | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager |
| GET | `/blood-bank/adverse-reactions/{reactionId}` | Get an adverse reaction | CenterAdmin, IntakeNurse, LabTechnician, InventoryManager |
| POST | `/blood-bank/recall-events` | Open a recall/lookback against a donor | InventoryManager |
| GET | `/blood-bank/recall-events` | List recall events, filterable | CenterAdmin, InventoryManager |
| GET | `/blood-bank/recall-events/{recallEventId}` | Get a recall event | CenterAdmin, InventoryManager |
| POST | `/blood-bank/inventory-buckets` | Create/initialize an inventory bucket | InventoryManager |
| GET | `/blood-bank/inventory-buckets` | List inventory buckets, filterable | CenterAdmin, InventoryManager, LabTechnician |
| GET | `/blood-bank/inventory-buckets/{bucketId}` | Get a bucket | CenterAdmin, InventoryManager, LabTechnician |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CENTER_NOT_FOUND` | 404 Not Found |
| `ERR_DONOR_NOT_FOUND` | 404 Not Found |
| `ERR_DEFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SCREENING_NOT_FOUND` | 404 Not Found |
| `ERR_DONATION_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_RESULT_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_REACTION_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_BUCKET_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DEFERRAL_DURATION` | 422 Unprocessable Entity |
| `ERR_COMPONENT_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_SLOT_WINDOW` | 422 Unprocessable Entity |
| `ERR_PLASMA_VOLUME_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ANNUAL_PLASMA_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STALE_SLOT_VERSION` | 412 Precondition Failed |
| `ERR_APPOINTMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DONATION_NOT_COLLECTED` | 409 Conflict |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_UNIT_NOT_RESERVED` | 409 Conflict |
| `ERR_UNIT_EXPIRED` | 409 Conflict |
| `ERR_DEFERRAL_NOT_ACTIVE` | 409 Conflict |
| `ERR_DONOR_NOT_ELIGIBLE` | 403 Forbidden |
| `ERR_SCREENING_NOT_PASSED` | 409 Conflict |
| `ERR_SEVERE_REACTION_BLOCKS_RELEASE` | 409 Conflict |
| `ERR_INTERVAL_NOT_ELAPSED` | 409 Conflict |
| `ERR_SLOT_WINDOW_OPEN` | 409 Conflict |
| `ERR_SLOT_NOT_BOOKABLE` | 409 Conflict |
| `ERR_DONOR_HAS_OPEN_APPOINTMENT` | 409 Conflict |
| `ERR_DUPLICATE_DIN` | 409 Conflict |
| `ERR_INFECTIOUS_DEFERRAL_NOT_LIFTABLE` | 409 Conflict |
| `ERR_CLOCK_NOT_MONOTONIC` | 409 Conflict |
