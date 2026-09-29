# Multi-Dose Adherence Mail Pharmacy API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a multi-dose adherence packaging and mail-order pharmacy. The business it describes takes a patient's whole medication regimen, pulls every prescription onto one common fill cycle, dispenses that cycle as a roll of date-and-time labelled pouches, verifies each pouch by imaging it against an expected pill count, and mails the result — splitting refrigerated and non-packable items into their own parcels. Around that physical flow sits a payer layer: each claim line must survive a refill-too-soon edit and a day-supply edit, a prescription that has run out of refills must be chased back to its prescriber, a traveling patient may be granted an early-supply exception, and every mid-cycle disruption must be resolved with money — a credit memo whose value is computed to the cent.

The API is consumed by five staff-facing actors and by patients themselves. A platform administrator configures payer plans and enrols patients. Pharmacy operations owns synchronization, cycle creation, the prescriber chase, split shipments and reissues. A verifying pharmacist exercises professional judgement: payer adjudication, second-person roll verification, rework decisions and travel-exception decisions. A packaging technician works the bench, building and packing rolls and capturing verification images. A prescriber writes prescriptions, answers refill-authorization chases and issues mid-cycle regimen changes. A patient reports doses taken and missed, confirms parcel pickup, requests travel exceptions and pauses or resumes their own auto-ship. The separation between these actors is a safety control, not a convenience: the technician who packed a roll may neither image its pouches nor sign its verification.

Everything in this specification is deterministic. All money is held as whole integer cents, all percentages as whole integers, and every rounding step is named explicitly at the point it occurs. All dates and timestamps are compared against a settable logical clock rather than wall-clock time, so a full lifecycle — a fill cycle opened, adjudicated, packed, verified, shipped, delivered, collected, then disrupted by a regimen change and partially reissued with a credit — can be replayed identically on demand. Consistency is immediate: every cascade described in this document is complete before the response that triggered it is returned.

## 2. Global Specifications

### 2.1. Actors, Authentication and Role-Based Access Control

Every request except the logical-clock setter must carry two headers:

- `X-User-ID` — the caller's opaque user identifier. For the `Patient` role this value is the patient's own `id`.
- `X-User-Role` — exactly one of `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician`, `Prescriber`, `Patient`.

If either header is absent or empty on any endpoint other than the logical-clock setter, the request fails with `ERR_UNAUTHENTICATED` and HTTP 401. If both headers are present but the role in `X-User-Role` is not listed for the addressed endpoint in section 4, the request fails with `ERR_UNAUTHORIZED` and HTTP 403. No role is a superset of another; each role is a distinct band of authority.

- **`PlatformAdmin`** — configures payer plans (the only role that may register one) and enrols patients alongside `PharmacyOperations`. May read every collection in the system but performs no pharmacy step: no adjudication, no bench work, no verification, no prescriber act, no pickup confirmation.
- **`PharmacyOperations`** — the operational owner. Exclusively performs regimen synchronization, the adherence review sweep, fill-cycle creation, shipment staging, dispatch, delivery recording, refill-authorization creation, chasing and escalation, and partial reissue. Shares patient enrolment with `PlatformAdmin`, prescription recording with `Prescriber`, and auto-ship changes, dose-event reporting and travel-exception requests with `Patient`. May read everything. May not configure plans, may not adjudicate, may not pack, may not verify or rework, may not decide travel exceptions, may not answer an authorization or issue a regimen change, and may not confirm pickup.
- **`VerifyingPharmacist`** — professional judgement. Exclusively adjudicates a fill cycle, verifies a pouch roll, sends a quarantined roll back for rework, and decides a travel exception. Shares pouch imaging (single-pouch and whole-roll) with `PackagingTechnician`. May read everything. May not create cycles, stage shipments or reissue; may not generate or pack a roll; may not touch the authorization chase; may not synchronize, change auto-ship posture, report dose events or run the adherence review.
- **`PackagingTechnician`** — the bench. Exclusively generates a pouch roll for a cycle and claims a roll as packed. Shares pouch imaging with `VerifyingPharmacist`. Reads are narrower than the other staff roles: this role may read patients by identifier, prescriptions, fill cycles, cycle lines, pouch rolls, pouches and shipments, but not insurance plans, the patient collection, credit memos, travel exceptions, refill authorizations or adherence events. May never verify or rework a roll, never adjudicate, never create plans, patients, prescriptions or cycles, and never write to a shipment.
- **`Prescriber`** — exclusively answers a refill-authorization request and exclusively issues a mid-cycle regimen change. Shares prescription recording with `PharmacyOperations`. Reads prescriptions and refill authorizations only. May not open, chase or escalate an authorization request — the pharmacy chases, the prescriber answers. May not touch cycles, rolls, pouches, shipments, patients, cycle lines or credit memos, and may not decide a travel exception.
- **`Patient`** — identity-backed: `X-User-ID` is a `Patient.id`. Exclusively confirms parcel pickup. Shares auto-ship changes, dose-event reporting and travel-exception requests with `PharmacyOperations`. Reads only their own patient record, adherence summary, prescriptions, fill cycles, cycle adherence-event stream, shipments, travel exceptions, credit memos and adherence events. May not read insurance plans, the patient collection, cycle lines, pouch rolls, pouches or refill authorizations, and performs no pharmacy step.

**Patient scoping.** When `X-User-Role` is `Patient`, the addressed resource must resolve to the caller. For a route addressed by patient identifier, that identifier must equal `X-User-ID`. For any other resource, the owning patient is resolved by walking the ownership edges — a shipment resolves through its fill cycle to that cycle's `patient_id`, a prescription resolves directly through its `patient_id`, a cycle line resolves through its cycle, a pouch through its roll and that roll's cycle — and the resulting patient identifier must equal `X-User-ID`. A mismatch fails with `ERR_PATIENT_SCOPE_VIOLATION` and HTTP 403. The same rule applies to list reads: a patient sees only their own rows. Note that scoping is evaluated *after* existence: a resource that does not exist yields its not-found error, not a scope violation.

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

### 2.3. Pagination, Ordering and List Filters

Every list read accepts two optional pagination parameters:

- `limit` — maximum number of rows to return. Default 10, minimum 1, maximum 100. A value outside 1 through 100 is a schema violation.
- `offset` — number of rows to skip before returning results. Default 0. A negative value is a schema violation.

List responses carry `limit`, `offset`, `total_count` and `has_more` in `meta`. `total_count` is the number of rows matching the filters *before* `limit` and `offset` are applied; `has_more` is true when the sum of `offset` and the number of returned rows is less than `total_count`. Single-resource reads omit the four pagination fields from `meta`.

Unless a specific read says otherwise, rows are returned in ascending `created_at` order, with ascending `id` as a deterministic tie-break. Two reads order differently: the adherence-event stream of one fill cycle is returned in ascending `occurred_at` order with ascending `created_at` as tie-break, and pouches are returned in ascending `pouch_index` order.

Every filter parameter is optional; when several are supplied they combine conjunctively, and an unrecognised filter value simply matches nothing rather than erroring (an enum-typed filter carrying a value outside its declared set is a schema violation). The available filters, by collection, are:

- Patients: `insurance_plan_id`, `autoship_status`, `sync_status`.
- Prescriptions: `patient_id`, `supersedes_rx_id`, `status`. Filtering by `supersedes_rx_id` resolves the successor chain minted by regimen changes.
- Fill cycles: `patient_id`, `reissue_of_cycle_id`, `vacation_exception_id`, `packaging_status`, `insurance_status`. Filtering by `reissue_of_cycle_id` resolves partial-reissue children; filtering by `vacation_exception_id` resolves travel-extended cycles.
- Cycle lines: `cycle_id`, `prescription_id`, `line_status`.
- Pouch rolls: `cycle_id`, `verification_status`.
- Pouches: `roll_id`, `verification_result`, `dose_slot`. The `roll_id` filter is the reverse edge from a roll to its pouches.
- Shipments: `cycle_id`, `shipment_kind`, `status`.
- Refill authorizations: `prescription_id`, `status`.
- Travel exceptions: `patient_id`, `status`.
- Credit memos: `patient_id`, `cycle_id`, `applied_to_cycle_id`, `reason`, `status`. `cycle_id` is the cycle a credit was issued against; `applied_to_cycle_id` is the later cycle that consumed it.
- Adherence events: `cycle_id`, `event_type`, `source`.

### 2.4. The Logical Clock

Every date and timestamp comparison in this domain — refill-too-soon elapsed days, the 72-hour prescriber response window, the 48-hour cold-chain separation buffer, the 5-day pickup grace period, the 28-day rolling adherence window, prescription expiry, travel-window validity — reads a single logical clock rather than the host's wall clock.

The clock is set through a test-only endpoint that accepts one field, `current_utc`, an ISO 8601 UTC timestamp. Until that endpoint is first called, the logical clock reads `2026-08-01T00:00:00Z`. The clock setter is the one endpoint exempt from authentication: it may be called by any of the six roles and does not require `X-User-ID` or `X-User-Role` to be present. Setting the clock mutates no business entity; its response body is an object carrying the new `current_utc` value.

Where this document says "the clock", it means the current logical-clock instant. Where it says "the clock date", it means that instant's calendar date in UTC. Timestamps written by the system — `packed_at`, `verified_at`, `imaged_at`, `staged_at`, `dispatched_at`, `delivered_at`, `pickup_confirmed_at`, `decided_at`, `issued_at`, `applied_at`, `first_sent_at`, `last_sent_at`, `no_response_recorded_at` and the derived `next_chase_due_at` — are all taken from the logical clock, never from wall time.

### 2.5. Resource Identity, Timestamps and Versioning

Every resource carries a server-generated `id`: an opaque UUID string with no type prefix. Identifiers are never reused and never reassigned.

Every resource except one also carries `created_at`, `updated_at` and `version`. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, both set from the logical clock at creation; `updated_at` is refreshed on every mutation. `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row, including mutations reached through a cascade from another endpoint. Where a section below says a version "increments", it means this counter advances by 1.

The single exception is the adherence event, which is an append-only audit record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after it is written. Nothing in this API deletes or edits an adherence event.

### 2.6. Money, Percentages and Rounding

All monetary amounts are integer counts of whole cents and are never expressed in fractional currency units. Copay rates are quoted per day: `generic_copay_cents_per_day`, `brand_copay_cents_per_day` and `specialty_copay_cents_per_day` on the payer plan.

Where a formula in section 3 divides, the intermediate value is an exact rational number and is *not* rounded until the step that explicitly names rounding. Two rounding disciplines are used, and they are never interchanged:

- **Half-up rounding to whole cents.** A non-negative amount whose fractional part is exactly one half rounds away from zero; anything below one half rounds down, anything above rounds up. This is the discipline used for a line's copay, for the cycle's final copay, and for each per-line credit in a partial reissue.
- **Floor to a whole percent.** The value is truncated toward zero. This is the discipline used for the refill-too-soon percentage and for both adherence scores. A floored percentage is never rounded up, so a value just short of a threshold stays just short of it.

Percentage thresholds are compared inclusively or exclusively exactly as each rule states, and the distinction is load-bearing. The plan's refill-too-soon threshold clears at the threshold value itself. The adherence pause gate fires strictly below its threshold, so a score exactly equal to the threshold does not pause auto-ship. The imaging confidence gate marks a read unreadable strictly below its minimum, so a confidence exactly equal to the minimum is readable.

Coinsurance is expressed as the percent the plan withholds, `coinsurance_pct`, so the patient's share factor is one hundred minus `coinsurance_pct`, divided by one hundred. A `coinsurance_pct` of zero means the patient pays the full per-day rate; a `coinsurance_pct` of one hundred means the patient pays nothing.

### 2.7. Interval and Date Semantics

Three different interval conventions coexist in this domain and are deliberately not unified. Confusing them produces off-by-one-day defects, so each is stated once here and referenced by name in section 3.

- **Half-open date windows.** A fill cycle covers `cycle_start_date` inclusive through `cycle_end_date` exclusive, where `cycle_end_date` is `cycle_start_date` advanced by `day_supply_days` calendar days. A cycle line covers `line_start_date` inclusive through `line_end_date` exclusive. Two half-open windows collide only when each one's start is strictly before the other's end; windows that merely touch, where one window's start equals the other's end, do not collide.
- **Closed-inclusive date segments.** A pouch roll covers `segment_start_date` through `segment_end_date`, both inclusive — `segment_end_date` is the last calendar date for which a pouch physically exists. Two closed segments collide when each one's start is on or before the other's end, so segments that merely abut, where one segment's start equals the other's end, *do* collide. This is the opposite outcome from the half-open cycle windows above.
- **Buffered instants.** The cold-chain separation rule compares two staging instants and treats them as conflicting when the absolute difference between them is strictly less than the 48-hour minimum gap. A separation of exactly 48 hours is permitted.

Day counts between two calendar dates are whole numbers of days. A day count is inclusive of its start date and exclusive of its end date unless the field is explicitly documented as inclusive. Prescription expiry is compared as a calendar date: a prescription whose `expiration_date` is strictly before the clock date is expired, and one whose `expiration_date` equals the clock date is still fillable.

### 2.8. The Two-Dimensional Fill-Cycle State Model

A fill cycle carries two independent state dimensions on the same row, and the two advance on different triggers.

`packaging_status` is the physical dimension. It begins at `DRAFT` and moves through `LINES_ADJUDICATED`, `ROLL_GENERATED`, `PACKED`, `VERIFIED` and `SHIPPED` to the terminal `CLOSED`, with `CANCELLED` as the other terminal value. It advances only on packaging triggers: adjudication, roll generation, packing, verification, the dispatch that completes the cycle, and pickup confirmation. It can also move backwards — from `PACKED` or `VERIFIED` back to `ROLL_GENERATED` — when verification fails or a regimen change supersedes a line.

`insurance_status` is the payer dimension. It begins at `NOT_ADJUDICATED` and reaches one of `EDITS_PENDING`, `CLEARED` or `REJECTED_TOO_SOON`, with `CLEARED` as its terminal value. It advances only on payer and authorization triggers: adjudication, a prescriber's answer to an authorization request, an escalation that drops a held line.

The two value sets are disjoint, so any state named in this document belongs unambiguously to one dimension. The critical consequence is that re-adjudicating a cycle whose `insurance_status` is `REJECTED_TOO_SOON` moves **only** the payer dimension: `packaging_status` stays at `LINES_ADJUDICATED` and is not reset to `DRAFT`, and the lines that already adjudicated successfully on the first pass are not touched a second time.

**Cascade discipline.** Every state change described in section 3 that says one row's change causes another row's change is a synchronous cascade completed before the response is returned. A cascade increments the `version` of every row it touches. Cascades are never partial: if a validation rejects a request, no part of its cascade is applied.

### 2.9. Stale-Version Protection

Two write operations require the caller to prove they are working from a current view of the parent row. Both fields are **required**, not optional — omitting one is a schema violation, not a silent pass.

- Creating a partial reissue against a fill cycle requires `expected_cycle_version` in the request body. If that value does not equal the addressed fill cycle's current `version`, the request fails with `ERR_STALE_CYCLE_VERSION` and HTTP 412. A reissue legitimately supersedes the tail of a cycle — trimming lines, truncating the roll segment and issuing a credit — so a second reissue derived from a pre-trim view of the cycle would credit days the first reissue already credited.
- Issuing a mid-cycle regimen change against a prescription requires `expected_prescription_version` in the request body. If that value does not equal the addressed prescription's current `version`, the request fails with `ERR_STALE_PRESCRIPTION_VERSION` and HTTP 412. A regimen change supersedes the prescription and mints a successor, so a change written from a stale view would branch a second successor off an already-superseded prescription.

The version check is evaluated against the *parent* row named above, not against any child the operation also touches, and it is evaluated early — before the addressed row's own state is examined. A reissue request that is both stale and aimed at a cycle in the wrong `packaging_status` returns the stale-version error. A regimen-change request that is both stale and aimed at a non-active prescription returns the stale-version error. No endpoint other than these two accepts a version field, and no endpoint accepts a version field for a row other than the one named above.

### 2.10. Segregation of Duties at the Packing Bench

Pack verification is a two-person control. When a packaging technician claims a roll as packed, that caller's `X-User-ID` is recorded as `packed_by_user_id` on the roll. From that moment:

- The user identified by `packed_by_user_id` may not capture a verification image for any pouch of that roll, whether through the single-pouch route or the whole-roll scanner route.
- The user identified by `packed_by_user_id` may not sign the roll's verification.

Either attempt fails with `ERR_SEGREGATION_OF_DUTIES` and HTTP 409. The control is on identity, not on role: a `PackagingTechnician` other than the packer may image the roll, and a `VerifyingPharmacist` may image it too. Because the pharmacist who signs verification is recorded as `verified_by_user_id`, the pack-and-verify pair is always two distinct users.

Sending a quarantined roll back for rework clears `packed_by_user_id`, `packed_at`, `verified_by_user_id` and `verified_at`, which means the identity constraint is released: after rework, any technician — including the original packer — may pack the roll again, and the constraint re-arms against whoever packs it that time.

### 2.11. Validation Ordering and Error Precedence

Validation rules are evaluated in strict ascending priority order. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied. Implementations must reproduce this ordering exactly, because many of the rules below can hold simultaneously on the same request and only the earliest one is observable.

| Priority | Error ID | HTTP | Scope and condition |
| --- | --- | --- | --- |
| 1 | `ERR_UNAUTHENTICATED` | 401 | Every endpoint except the logical-clock setter: `X-User-ID` is absent or empty, or `X-User-Role` is absent or empty. |
| 2 | `ERR_UNAUTHORIZED` | 403 | Every endpoint: the role in `X-User-Role` is not listed for that endpoint in section 4. |
| 3 | `ERR_INVALID_REQUEST` | 400 | Every endpoint: a required input field is missing or null; a field has the wrong JSON type; an enum field carries a value outside its declared set; an integer falls outside its declared range; a date or timestamp is not ISO 8601; `limit` is outside 1 through 100 or `offset` is negative; a date-range field pair has its start after its end; `dose_times` is empty or contains a duplicate slot; an array field that must be non-empty is empty. |
| 4 | `ERR_INSURANCE_PLAN_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_FILL_CYCLE_NOT_FOUND`, `ERR_CYCLE_LINE_NOT_FOUND`, `ERR_POUCH_ROLL_NOT_FOUND`, `ERR_POUCH_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_REFILL_AUTHORIZATION_NOT_FOUND`, `ERR_VACATION_EXCEPTION_NOT_FOUND`, `ERR_CREDIT_MEMO_NOT_FOUND`, `ERR_ADHERENCE_EVENT_NOT_FOUND` | 404 | Every endpoint addressed by a path identifier: no row of the addressed entity has that identifier. The error chosen is the one naming the addressed entity. |
| 5 | `ERR_INSURANCE_PLAN_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_FILL_CYCLE_NOT_FOUND`, `ERR_VACATION_EXCEPTION_NOT_FOUND` | 404 | Every endpoint accepting a foreign key in its body: any of `insurance_plan_id`, `patient_id`, `prescription_id`, `cycle_id`, `vacation_exception_id`, a member of `replacement_prescription_ids`, or a member of `force_pouch_prescription_ids` names no existing row. |
| 6 | `ERR_PATIENT_SCOPE_VIOLATION` | 403 | Every endpoint when `X-User-Role` is `Patient`: the addressed resource's owning patient — walked up through shipment to fill cycle to patient, or prescription to patient — is not the caller's `X-User-ID`. |
| 7 | `ERR_STALE_CYCLE_VERSION`, `ERR_STALE_PRESCRIPTION_VERSION` | 412 | Partial reissue and regimen change respectively: the submitted `expected_cycle_version` or `expected_prescription_version` does not equal the parent row's current `version`. |
| 8 | `ERR_PATIENT_NOT_SYNCHRONIZED` | 409 | Fill-cycle creation: the patient's `sync_status` is not `SYNCED`, so no `anchor_fill_day` or `sync_mode` has been pinned. |
| 9 | `ERR_AUTOSHIP_PAUSED` | 409 | Fill-cycle creation, adjudication and partial reissue: the patient's `autoship_status` is not `ACTIVE`. |
| 10 | `ERR_INVALID_CYCLE_STATE` | 409 | Adjudication: `packaging_status` is not `DRAFT` or `LINES_ADJUDICATED`, or `insurance_status` is not `NOT_ADJUDICATED` or `REJECTED_TOO_SOON` (a cleared cycle cannot re-adjudicate). Roll generation: `packaging_status` is not `LINES_ADJUDICATED`. Shipment staging with `shipment_kind` `POUCH_ROLL`: `packaging_status` is not `VERIFIED` or `SHIPPED`. Shipment staging with `shipment_kind` `COLD_CHAIN` or `NON_PACKABLE_LOOSE`: `packaging_status` is not one of `LINES_ADJUDICATED`, `ROLL_GENERATED`, `PACKED`, `VERIFIED`, `SHIPPED`. Partial reissue: `packaging_status` is not one of `ROLL_GENERATED`, `PACKED`, `VERIFIED`. |
| 11 | `ERR_CYCLE_NOT_CLEARED` | 409 | Roll generation: `insurance_status` is `EDITS_PENDING`, so authorization edits are still open. |
| 12 | `ERR_INVALID_ROLL_STATE` | 409 | Packing: the roll's `verification_status` is not `BUILT`. Verification: `verification_status` is not `PACKED`, or at least one pouch of the roll still has `verification_result` `PENDING`. Rework: `verification_status` is not `FAILED_QUARANTINED`. Single-pouch imaging and whole-roll imaging: the roll's `verification_status` is not `PACKED`. |
| 13 | `ERR_IMAGE_ALREADY_CAPTURED` | 409 | Single-pouch imaging: the pouch's `verification_result` is not `PENDING`, so an image was already captured for this pack attempt. |
| 14 | `ERR_INVALID_SHIPMENT_STATE` | 409 | Dispatch: `status` is not `STAGED`. Delivery: `status` is not `IN_TRANSIT`. Pickup confirmation: `status` is not `DELIVERED`. |
| 15 | `ERR_INVALID_AUTH_STATE` | 409 | Chase: `status` is not `SENT` or `NO_RESPONSE`. Escalation: `status` is not `NO_RESPONSE`. Prescriber response: `status` is not `SENT` or `ESCALATED`. |
| 16 | `ERR_INVALID_VACATION_STATE` | 409 | Travel-exception decision: `status` is not `SUBMITTED`. |
| 17 | `ERR_INVALID_PRESCRIPTION_STATE` | 409 | Regimen change: the prescription's `status` is not `ACTIVE`. Authorization creation: the prescription's `status` is not `ACTIVE` or `PENDING_AUTHORIZATION`. |
| 18 | `ERR_SEGREGATION_OF_DUTIES` | 409 | Verification, whole-roll imaging and single-pouch imaging: `X-User-ID` equals the roll's `packed_by_user_id`. |
| 19 | `ERR_CONTROLLED_SUBSTANCE_NO_OVERRIDE` | 422 | Travel-exception decision with `decision` `APPROVE_PHARMACIST` or `APPROVE_PAYER_OVERRIDE`: at least one prescription of the patient with `status` `ACTIVE` has `is_controlled` true. |
| 20 | `ERR_COLD_CHAIN_NOT_PACKABLE` | 422 | Adjudication: a prescription named in `force_pouch_prescription_ids` has `refrigerated` true. A refrigerated drug can never be routed into a pouch roll. |
| 21 | `ERR_COLD_CHAIN_PACKAGING_INVALID` | 422 | Shipment staging: `shipment_kind` is `COLD_CHAIN` and `packaging` is `STANDARD`, or `shipment_kind` is not `COLD_CHAIN` and `packaging` is `INSULATED_GEL` or `INSULATED_DRY_ICE`. |
| 22 | `ERR_NON_PACKABLE_IN_POUCH_ROUTE` | 422 | Adjudication: a prescription named in `force_pouch_prescription_ids` has `packable` false because its `form` is not `TABLET` or `CAPSULE`. |
| 23 | `ERR_NO_PACKABLE_LINES` | 422 | Roll generation: the cycle has no cycle line whose `line_status` is `ADJUDICATED` and whose `packable_route` is `POUCH`. |
| 24 | `ERR_NO_LINES_FOR_SHIPMENT_KIND` | 422 | Shipment staging: no cycle line with `line_status` `ADJUDICATED` or `PACKED_OUT` maps to the requested `shipment_kind` (`POUCH_ROLL` needs a `POUCH` line, `COLD_CHAIN` needs a `COLD_CHAIN` line, `NON_PACKABLE_LOOSE` needs a `LOOSE_SPLIT` line), or a shipment of that kind already exists for the cycle with a `status` other than `CANCELLED` or `EXCEPTION_RETURNED`. |
| 25 | `ERR_RX_PENDING_AUTHORIZATION` | 409 | Roll generation: a cycle line with `line_status` `ADJUDICATED` references a prescription whose `status` is not `ACTIVE`. |
| 26 | `ERR_ROLL_NOT_VERIFIED` | 409 | Dispatch: `shipment_kind` is `POUCH_ROLL` and the cycle's pouch roll has `verification_status` other than `PASSED`. |
| 27 | `ERR_NO_APPROVED_VACATION_EXCEPTION` | 422 | Adjudication carrying `vacation_exception_id`: the referenced travel exception's `patient_id` is not the cycle's `patient_id`, or its `status` is neither `PHARMACIST_APPROVED` nor `PAYER_OVERRIDE_APPROVED`. |
| 28 | `ERR_CYCLE_WINDOW_OVERLAP` | 409 | Fill-cycle creation: under half-open window semantics, another fill cycle of the same patient whose `packaging_status` is neither `CANCELLED` nor `CLOSED` and whose `is_partial_reissue` is false has the new cycle's `cycle_start_date` strictly before its `cycle_end_date` and its own `cycle_start_date` strictly before the new `cycle_end_date`. Touching windows are legal. |
| 29 | `ERR_REISSUE_SEGMENT_OVERLAP` | 409 | Roll generation: under closed-inclusive segment semantics, the segment the new roll would occupy collides with an existing pouch roll of the same patient whose `verification_status` is not `FAILED_QUARANTINED` — the new `segment_start_date` is on or before the existing `segment_end_date` and the existing `segment_start_date` is on or before the new `segment_end_date`. Abutting segments do collide. |
| 30 | `ERR_COLD_CHAIN_GAP_VIOLATION` | 409 | Shipment staging with `shipment_kind` `COLD_CHAIN`: another cold-chain shipment of the same patient whose `status` is neither `CANCELLED` nor `EXCEPTION_RETURNED` has a `staged_at` whose absolute difference from the clock is strictly less than 48 hours. Exactly 48 hours apart is legal. |
| 31 | `ERR_VACATION_WINDOW_INVALID` | 422 | Travel-exception creation: `travel_start_date` is before the clock date, or the number of days from `travel_start_date` through `travel_end_date` counted inclusively is less than `requested_extra_days`. |
| 32 | `ERR_CHASE_TOO_EARLY` | 409 | Chase: `status` is `SENT` and the clock is strictly before `next_chase_due_at`, so the 72-hour prescriber response window has not elapsed. |
| 33 | `ERR_REISSUE_DATE_OUT_OF_WINDOW` | 422 | Partial reissue: `effective_date` is on or before the cycle's `cycle_start_date`, or on or after the cycle's `cycle_end_date`. |
| 34 | `ERR_CHASE_LIMIT_REACHED` | 409 | Chase: `status` is `SENT` and `chase_round` has already reached 3, so the request must be escalated instead. |
| 35 | `ERR_ESCALATION_PREMATURE` | 409 | Escalation: `chase_round` is below 3. |
| 36 | `ERR_REWORK_LIMIT_REACHED` | 409 | Rework: `rework_count` has already reached 2. |
| 37 | `ERR_DAY_SUPPLY_EXCEEDS_ALLOWANCE` | 422 | Adjudication: for at least one cycle line the computed `days_supply_filled` exceeds the computed `allowance_days`. |
| 38 | `ERR_VACATION_LIMIT_EXCEEDED` | 422 | Travel-exception creation: the patient's `vacation_exceptions_used_this_year` is greater than or equal to the plan's `vacation_overrides_per_year`. |
| 39 | `ERR_PAYER_OVERRIDE_NOT_ALLOWED` | 422 | Travel-exception decision with `decision` `APPROVE_PAYER_OVERRIDE`: the patient's plan has `allows_payer_vacation_override` false. |
| 40 | `ERR_INVALID_APPROVED_DAYS` | 422 | Travel-exception decision with an approving decision: `approved_extra_days` is absent, below 1, or greater than `requested_extra_days`. Travel-exception decision with `DENY`: `denial_reason` is absent. Prescriber response with `APPROVE`: `approved_refills` is absent or greater than `requested_refills`. Prescriber response with `DENY`: `denial_reason` is absent. |
| 41 | `ERR_DUPLICATE_AUTH_REQUEST` | 409 | Authorization creation: another refill authorization request for the same `prescription_id` has `status` `SENT`, `NO_RESPONSE` or `ESCALATED`. |
| 42 | `ERR_INVALID_ANCHOR_DAY` | 422 | Synchronization: `anchor_fill_day` is greater than 28 — a day-of-month that not every month has. A value outside 1 through 31 is a schema range violation caught at priority 3 instead. |
| 43 | `ERR_NO_ACTIVE_PRESCRIPTIONS` | 422 | Synchronization and fill-cycle creation: after the expiry sweep the patient has no prescription whose `status` is `ACTIVE`. |
| 44 | `ERR_REFILL_TOO_SOON` | 409 | Roll generation: the cycle's `insurance_status` is `REJECTED_TOO_SOON`, so the payer's refill-too-soon edit is unresolved and no roll may be produced. |
| 45 | `ERR_NOTHING_TO_REISSUE` | 422 | Partial reissue: no cycle line of the cycle has `line_status` `SUPERSEDED_PENDING_REISSUE` and no `ADJUDICATED` line references a prescription named in `replacement_prescription_ids`. |

Two ordering consequences deserve emphasis. First, existence (priorities 4 and 5) precedes patient scoping (priority 6): a patient addressing a nonexistent row gets the not-found error, not a scope violation. Second, the stale-version check (priority 7) precedes every state and business check, so a stale reissue or regimen change reports the version conflict even when other conditions would also have rejected it.

### 2.12. The Credit Ledger

Money owed back to a patient is held as credit memos rather than as a mutable balance. Each memo records the `patient_id` it belongs to, the `cycle_id` it was issued against, its `reason`, its `amount_cents`, its `status` and its `issued_at`. Four reasons exist, and each is minted by exactly one event: `PARTIAL_REISSUE` when the untaken tail of a cycle is reissued, `COLD_CHAIN_EXCURSION` when a refrigerated parcel is returned after a temperature excursion, `ROUNDING_TRUEUP` when the provisional and final copays of a cycle differ, and `FAILED_VERIFICATION` as a goodwill gesture of 500 cents when a roll fails pack verification.

A memo begins at `ISSUED`. The patient's `credit_balance_cents` is always the sum of `amount_cents` over that patient's memos whose `status` is `ISSUED`; issuing a memo raises it by the memo's `amount_cents`.

A memo leaves `ISSUED` in one of two ways. It reaches `APPLIED` when a **later** cycle of the same patient adjudicates: outstanding memos are consumed in ascending `created_at` order while the adjudicating cycle still has copay left to offset, and a memo whose `cycle_id` is the adjudicating cycle itself is never applied to that cycle. Applying a memo stamps its `applied_to_cycle_id` with the consuming cycle and its `applied_at` with the clock, raises that cycle's `credit_applied_cents` by the memo's `amount_cents`, and drops the patient's `credit_balance_cents` by the same amount. Alternatively, a memo reaches `VOIDED` when the patient's auto-ship is cancelled outright: every `ISSUED` memo of that patient becomes `VOIDED` and `credit_balance_cents` is set to zero, because an unredeemed credit has no future fill to land on. Both `APPLIED` and `VOIDED` are terminal; a memo never returns to `ISSUED`.

## 3. Business Logic & Workflows

### 3.1. Payer Plans, Patient Enrolment and Regimen Synchronization

**Registering a payer plan.** Only `PlatformAdmin` may register an insurance plan. The caller supplies `payer_name` (the payer or pharmacy-benefit-manager trade name), `bin_number` (the six-digit routing BIN used on the claim), and the three per-day copay rates `generic_copay_cents_per_day`, `brand_copay_cents_per_day` and `specialty_copay_cents_per_day`, each of which must be zero or greater. Four further fields are optional and take a default when omitted: `refill_too_soon_threshold_pct` defaults to 75 and must lie between 0 and 100; `max_day_supply_days` defaults to 90 and must lie between 1 and 365; `vacation_overrides_per_year` defaults to 1 and must lie between 0 and 12; `coinsurance_pct` defaults to 20 and must lie between 0 and 100. The boolean `allows_payer_vacation_override` defaults to false, and when false the payer refuses payer-level travel overrides entirely, leaving only a pharmacist-level approval possible. A plan is created with `version` 1.

**Enrolling a patient.** `PlatformAdmin` and `PharmacyOperations` may enrol a patient, supplying `full_name`, `date_of_birth` as an ISO 8601 calendar date, `email` (the address used for roll and pickup notifications), `state_code` (the two-letter shipping state) and `insurance_plan_id`, the payer whose edits govern every fill for this patient. The new patient starts deliberately inert: `sync_status` is `UNSYNCED`, `anchor_fill_day`, `sync_mode` and `next_cycle_start_date` are all null, `autoship_status` is `ACTIVE`, `pause_reason` is null, `adherence_score_pct` is 100, `consecutive_missed_pickups` is 0, `credit_balance_cents` is 0, `vacation_exceptions_used_this_year` is 0, and `version` is 1. Because `sync_status` is `UNSYNCED`, no fill cycle can yet be opened for this patient.

**Recording a prescription.** `Prescriber` and `PharmacyOperations` may record a prescription. The caller supplies `patient_id`, `prescriber_npi` (the ten-digit prescriber NPI that becomes the refill-authorization destination), `drug_name`, `ndc`, `strength` as free text such as a milligram figure, `form` (one of `TABLET`, `CAPSULE`, `VIAL`, `INHALER`, `INJECTION_PEN`, `LIQUID`), `copay_tier` (one of `GENERIC`, `PREFERRED_BRAND`, `SPECIALTY`, selecting which plan rate applies), `dose_times` (a non-empty array of distinct slots drawn from `MORNING`, `NOON`, `EVENING`, `BEDTIME`), `quantity_per_dose` (at least 1 — the units placed in each pouch at each of that drug's slots), `days_supply_written` (between 1 and 90), `refills_authorized` (zero or greater), `written_date` and `expiration_date`. Optionally the caller supplies `refrigerated` (default false — true when the item must move through a cold chain and can never enter a pouch), `is_controlled` (default false — true for a scheduled controlled substance, which caps day supply and forbids travel early-supply overrides), and the prior-fill history `last_dispensed_date` (default null for a never-filled prescription) and `last_dispensed_days_supply` (default 0).

The system computes `packable` and the caller may not supply it: `packable` is true exactly when `form` is `TABLET` or `CAPSULE` **and** `refrigerated` is false. The new prescription starts with `status` `ACTIVE`, `refills_remaining` equal to `refills_authorized`, `refills_consumed` 0, `days_dispensed_total` 0, `supersedes_rx_id` null, `prior_last_dispensed_date` null, `prior_last_dispensed_days_supply` 0, `sync_bridge_days` 0, `sync_trim_days` 0 and `version` 1. The invariant that `refills_remaining` plus `refills_consumed` equals `refills_authorized` holds after every mutation of the prescription, including every dispense, every reversal and every re-authorization. `days_dispensed_total` is the running sum of `days_supply_filled` over this prescription's lines whose `line_status` is `ADJUDICATED`, `PACKED_OUT` or `REISSUED`.

**Synchronizing the regimen.** Synchronization is exclusive to `PharmacyOperations` and is the act that makes a patient fillable. The caller supplies `anchor_fill_day`, the day-of-month all medications are pulled onto, and `sync_mode`, the alignment policy. The schema accepts `anchor_fill_day` between 1 and 31, but the business ceiling is 28: a value from 29 through 31 is rejected with `ERR_INVALID_ANCHOR_DAY`, because those days do not exist in every month, while a value outside 1 through 31 is a schema violation caught earlier. Synchronization requires the patient's `autoship_status` to be `ACTIVE` or `PAUSED_PATIENT`, and requires at least one prescription of the patient to survive the expiry sweep described next; if none does, the request fails with `ERR_NO_ACTIVE_PRESCRIPTIONS`.

Synchronization performs three things in order. First it sweeps expiry: every prescription of the patient whose `status` is `ACTIVE` and whose `expiration_date` is strictly before the clock date moves to `status` `EXPIRED`, is excluded from the synchronization set and will never appear on a future cycle's lines; each swept prescription's `version` increments. Second it pins the schedule: `anchor_fill_day` and `sync_mode` are stored, `sync_status` becomes `SYNCED`, and `next_cycle_start_date` is computed as the earliest calendar date on or after the clock date whose day-of-month equals `anchor_fill_day`. Third it projects the alignment: for every remaining prescription with `status` `ACTIVE`, `sync_bridge_days` and `sync_trim_days` are written according to the alignment rules below, measured against `next_cycle_start_date`. The patient's `version` increments by 1. Synchronization may be repeated; each run re-pins the anchor, re-sweeps expiry and re-projects the alignment.

**The alignment rules.** Medication synchronization pulls every prescription onto one common fill cycle, and the day supply dispensed on a line depends on how much of the previous fill the patient still holds when the cycle starts. Begin by locating the date through which the patient is already covered: it is `last_dispensed_date` advanced by `last_dispensed_days_supply` days. When `last_dispensed_date` is null the patient holds nothing, and the covered-through date is taken to be the cycle's own start date. From that, two non-negative day counts follow. The gap is the number of days by which the cycle start date falls after the covered-through date, or zero if it does not. The overlap is the number of days by which the covered-through date falls after the cycle start date, or zero if it does not. At most one of the two is non-zero.

A patient is pinned to exactly one of two irreconcilable policies, and the policy is never re-chosen at cycle creation:

- Under `BRIDGE_TO_START`, the fill is **lengthened** so the patient is covered from the day their current supply runs out through the end of the common cycle. `bridge_days_applied` is the gap, `trim_days_applied` is zero, and `days_supply_filled` is the cycle's `day_supply_days` plus the gap.
- Under `TRIM_TO_START`, the fill is **shortened** so the on-hand supply is burned down first and the next cycle lands exactly on the anchor day. `bridge_days_applied` is zero, `trim_days_applied` is the overlap, and `days_supply_filled` is the cycle's `day_supply_days` minus the overlap, floored at zero so it is never negative.

The line's own window follows from that: `line_start_date` is the cycle's `cycle_start_date` moved **earlier** by `bridge_days_applied` days and is inclusive, and `line_end_date` is `line_start_date` advanced by `days_supply_filled` days and is exclusive. The bridge days therefore sit *before* the common cycle start — they cover the gap between on-hand exhaustion and the anchor day — so a bridged line still ends exactly at `cycle_start_date` advanced by the cycle's `day_supply_days`. Under `TRIM_TO_START` there are no bridge days, so `line_start_date` always equals `cycle_start_date`.

### 3.2. Opening a Fill Cycle and Staging Its Claim Lines

Opening a fill cycle is exclusive to `PharmacyOperations`. The caller supplies `patient_id` and `cycle_start_date`, and may optionally supply `day_supply_days` (default 28, valid from 1 through 90) and `sync_mode` to override the patient's pinned policy for this one cycle. When `sync_mode` is omitted the cycle copies the patient's `sync_mode`.

Four gates are checked in this order, and the first one that holds returns. The patient's `sync_status` must be `SYNCED`, otherwise `ERR_PATIENT_NOT_SYNCHRONIZED`. The patient's `autoship_status` must be `ACTIVE`, otherwise `ERR_AUTOSHIP_PAUSED` — a paused or cancelled auto-ship blocks cycle creation outright. The new cycle's half-open window must not collide with any live cycle of the same patient, otherwise `ERR_CYCLE_WINDOW_OVERLAP`; only cycles whose `packaging_status` is neither `CANCELLED` nor `CLOSED` and whose `is_partial_reissue` is false participate in that test, so a partial-reissue child never blocks a later cycle and a closed or cancelled cycle never blocks anything. Finally the patient must have at least one prescription with `status` `ACTIVE`, otherwise `ERR_NO_ACTIVE_PRESCRIPTIONS`.

The new cycle is created with `cycle_end_date` computed as `cycle_start_date` advanced by `day_supply_days` days, exclusive; `packaging_status` `DRAFT`; `insurance_status` `NOT_ADJUDICATED`; `is_partial_reissue` false; `reissue_of_cycle_id` null; `vacation_exception_id` null; `approved_vacation_extra_days` 0; `reissue_required` false; `roll_pouch_count` 0; `total_copay_cents` 0; `final_copay_cents` null; `reissue_fee_cents` 0; `credit_applied_cents` 0; `rounding_delta_cents` null; and `version` 1.

Creation also stages the claim: one cycle line is created per prescription of the patient whose `status` is `ACTIVE`, in ascending prescription `created_at` order. Each staged line records its `cycle_id` and `prescription_id` and starts with `line_status` `PLANNED`, `hold_reason` null, and every computed figure at its zero default — `days_supply_filled`, `bridge_days_applied`, `trim_days_applied`, `quantity_dispensed`, `refill_pct_used`, `allowance_days` and `copay_cents` all 0, with `packable_route`, `line_start_date` and `line_end_date` not yet determined. Nothing is priced, routed or dispensed at creation; a `DRAFT` cycle is a proposal, and it is the only `packaging_status` from which an auto-ship pause can cancel a cycle outright.

### 3.3. Payer Adjudication: Edits, Holds, Routing and the Provisional Copay

Adjudication is exclusive to `VerifyingPharmacist` and is the single operation that runs every payer edit over the cycle. Its body carries two optional fields: `force_pouch_prescription_ids`, an array of prescription identifiers the pharmacist wants routed into the pouch roll, and `vacation_exception_id`, an approved travel exception to consume.

**Entry gates, in evaluation order.** The patient's `autoship_status` must be `ACTIVE`, otherwise `ERR_AUTOSHIP_PAUSED`. The cycle's `packaging_status` must be `DRAFT` or `LINES_ADJUDICATED` and its `insurance_status` must be `NOT_ADJUDICATED` or `REJECTED_TOO_SOON`, otherwise `ERR_INVALID_CYCLE_STATE`; a cycle already `CLEARED` can never re-adjudicate. Every prescription named in `force_pouch_prescription_ids` must have `refrigerated` false, otherwise `ERR_COLD_CHAIN_NOT_PACKABLE`, and must have `packable` true, otherwise `ERR_NON_PACKABLE_IN_POUCH_ROUTE` — the refrigeration check is reported first when both hold. When `vacation_exception_id` is supplied, the referenced travel exception's `patient_id` must equal the cycle's `patient_id` and its `status` must be `PHARMACIST_APPROVED` or `PAYER_OVERRIDE_APPROVED`, otherwise `ERR_NO_APPROVED_VACATION_EXCEPTION`. Lastly, once every line's figures have been computed, no line may have `days_supply_filled` greater than its `allowance_days`, otherwise `ERR_DAY_SUPPLY_EXCEEDS_ALLOWANCE`; this check is evaluated across all lines before any line's state or any prescription is committed, so a single over-supplied line aborts the entire adjudication with nothing written.

**Consuming a travel exception.** When a valid `vacation_exception_id` is supplied, the cycle stamps that identifier and sets `approved_vacation_extra_days` to the exception's `approved_extra_days`. Both approval kinds widen the day-supply allowance; only `PAYER_OVERRIDE_APPROVED` also waives the refill-too-soon edit, because only that kind has `waives_refill_too_soon` true.

**The refill-too-soon edit.** For each line the system computes `refill_pct_used`, the percent of the previous day supply the patient has consumed by the cycle's start. When the prescription's `last_dispensed_date` is null the patient has no prior fill, and `refill_pct_used` is 100 — a first fill always clears. Otherwise, count the elapsed days from `last_dispensed_date` to the cycle's `cycle_start_date`, multiply by one hundred, divide by the prescription's `last_dispensed_days_supply`, and floor the result to a whole percent. The edit clears when `refill_pct_used` is greater than or equal to the plan's `refill_too_soon_threshold_pct` — the comparison is **inclusive**, so a value exactly at the threshold clears — or when the cycle carries a travel exception whose `waives_refill_too_soon` is true. A line that fails the edit becomes `HELD_TOO_SOON` with `hold_reason` `REFILL_TOO_SOON`.

**The day-supply edit.** For each line the system computes `allowance_days`, the maximum number of days the plan will fund on that line, by folding four independent ceilings together with successive minima. Start with the smallest of three values: the plan's `max_day_supply_days`; the prescription's `days_supply_written` multiplied by one more than its `refills_remaining`; and the cycle's `day_supply_days` plus the line's `bridge_days_applied` plus the cycle's `approved_vacation_extra_days`. Then, if the prescription has `is_controlled` true, take the smaller of that result and 30. Then, if the prescription has `refrigerated` true, take the smaller of that result and 30. The final value is `allowance_days`. Note that the third ceiling moves in step with the fill: bridge days widen the ceiling exactly as much as they lengthen the line, and an attached travel exception widens it by `approved_vacation_extra_days`.

**Routing.** Each line's `packable_route` is determined by the prescription: `COLD_CHAIN` when `refrigerated` is true, `POUCH` when `refrigerated` is false and `packable` is true, and `LOOSE_SPLIT` otherwise — that is, a non-refrigerated item whose `form` is not `TABLET` or `CAPSULE`. Refrigerated items never enter a pouch roll under any circumstance.

**Quantities and the provisional copay.** For each line, `quantity_dispensed` is the prescription's `quantity_per_dose` multiplied by the number of entries in its `dose_times`, multiplied by the line's `days_supply_filled`. The line's copay begins as an exact unrounded amount: choose the per-day rate by `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` — multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the plan's `coinsurance_pct`, and divide by one hundred. That exact value is then rounded half-up to whole cents and stored as `copay_cents`. The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`. This round-each-line-then-sum discipline is the *provisional* figure; it is deliberately distinct from the final figure computed at dispatch, and the difference between them is later refunded. Lines that are held, excluded, superseded or credited contribute nothing to `total_copay_cents`.

**Per-line outcome.** Each `PLANNED` line resolves to exactly one of three states. It becomes `HELD_TOO_SOON` with `hold_reason` `REFILL_TOO_SOON` when the refill-too-soon edit fails. Otherwise it becomes `HELD_AUTH` with `hold_reason` `NO_REFILLS_REMAINING` when the prescription's `refills_remaining` is zero, and that prescription simultaneously moves from `status` `ACTIVE` to `PENDING_AUTHORIZATION` with its `version` incremented. Otherwise it becomes `ADJUDICATED`.

**Stamping the dispense.** Every line that becomes `ADJUDICATED` writes the dispense onto its prescription, and the order of writes matters because the pre-dispense history must survive for a possible reversal. First the current history is preserved: `prior_last_dispensed_date` takes the current value of `last_dispensed_date` and `prior_last_dispensed_days_supply` takes the current value of `last_dispensed_days_supply`. Only then is the new history written: `last_dispensed_date` becomes the line's `line_start_date` — which equals the cycle's `cycle_start_date` whenever no bridge days were applied — and `last_dispensed_days_supply` becomes the line's `days_supply_filled`. Then `days_dispensed_total` rises by the line's `days_supply_filled`, `refills_remaining` falls by 1 and `refills_consumed` rises by 1. The prescription's `version` increments.

**Cycle outcome.** The packaging dimension moves from `DRAFT` to `LINES_ADJUDICATED`. The payer dimension resolves by counting held lines: if at least one line ended `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and it becomes `CLEARED`. The refill-too-soon outcome dominates the authorization outcome when both kinds of hold are present.

**Applying credit.** After `total_copay_cents` is stamped, outstanding credit is consumed as described in the credit-ledger section: the patient's memos with `status` `ISSUED` are taken in ascending `created_at` order while copay remains to be offset, each becoming `APPLIED` with `applied_to_cycle_id` and `applied_at` stamped, the cycle's `credit_applied_cents` accumulating the applied amounts and the patient's `credit_balance_cents` falling to the sum of the memos still `ISSUED`. A memo whose `cycle_id` is this cycle is not applied to this cycle. The cycle's `version` increments by 1.

**Re-adjudication after a refill-too-soon rejection.** A cycle sitting at `packaging_status` `LINES_ADJUDICATED` with `insurance_status` `REJECTED_TOO_SOON` may be adjudicated again, and there are exactly two ways to clear it: wait until enough days have elapsed that `refill_pct_used` reaches the plan's `refill_too_soon_threshold_pct` and re-adjudicate, or attach a `PAYER_OVERRIDE_APPROVED` travel exception through `vacation_exception_id` and re-adjudicate. On such a re-run the refill-too-soon edit is waived or satisfied for every line; each `HELD_TOO_SOON` line is recomputed — its `allowance_days` widening by `approved_vacation_extra_days` — becomes `ADJUDICATED` and stamps its dispense. Lines that were already `ADJUDICATED` on the first pass are **not** recomputed and their dispense is **not** stamped a second time. The cycle's `total_copay_cents` is recomputed, `insurance_status` becomes `CLEARED`, and `packaging_status` is not touched: it remains `LINES_ADJUDICATED`.

### 3.4. Chasing the Prescriber for Refill Authorization

When adjudication holds a line because the prescription has no refills left, the pharmacy must chase the prescriber. Opening the chase is exclusive to `PharmacyOperations`; answering it is exclusive to `Prescriber`. The division is deliberate: the pharmacy chases, the prescriber answers, and neither may do the other's act.

**Opening a request.** The caller supplies `prescription_id` and `requested_refills`, which must be between 1 and 12. The prescription's `status` must be `ACTIVE` or `PENDING_AUTHORIZATION`, otherwise `ERR_INVALID_PRESCRIPTION_STATE` — a superseded, discontinued or expired prescription cannot be chased. No other request for the same `prescription_id` may currently have `status` `SENT`, `NO_RESPONSE` or `ESCALATED`, otherwise `ERR_DUPLICATE_AUTH_REQUEST`; at most one chase is open per prescription at a time. The new request copies `prescriber_npi` from the prescription and starts with `status` `SENT`, `chase_round` 0, `escalation_level` 0, `first_sent_at` and `last_sent_at` both at the clock, `next_chase_due_at` at the clock advanced by 72 hours, `no_response_recorded_at` null, `approved_refills` null, `denial_reason` null and `version` 1.

**One chase operation, two effects.** A single operation drives the chase loop, and what it does depends on the current `status`. It is available only from `SENT` or `NO_RESPONSE`, otherwise `ERR_INVALID_AUTH_STATE`.

- From `SENT` it records the prescriber's silence. The clock must have reached `next_chase_due_at`; if the clock is strictly earlier, the request fails with `ERR_CHASE_TOO_EARLY`, because the 72-hour response window has not elapsed. `chase_round` must still be below 3; if it has already reached 3 the request fails with `ERR_CHASE_LIMIT_REACHED` and the caller must escalate instead. On success `status` becomes `NO_RESPONSE`, `chase_round` rises by 1 and `no_response_recorded_at` is set to the clock.
- From `NO_RESPONSE` it re-sends and restarts the window. There is no timing gate on this direction. `status` returns to `SENT`, `last_sent_at` is set to the clock, and `next_chase_due_at` is set to the clock advanced by 72 hours.

The request's `version` increments on either effect. The loop therefore alternates `SENT` to `NO_RESPONSE` to `SENT`, and `chase_round` rises only on the silence-recording direction.

**Escalating.** Escalation is available only from `NO_RESPONSE`, otherwise `ERR_INVALID_AUTH_STATE`, and only once `chase_round` has reached 3, otherwise `ERR_ESCALATION_PREMATURE`. On success `status` becomes `ESCALATED` and `escalation_level` becomes 1. Escalation also has a conditional consequence for the held claim: if the clock date has reached the `cycle_start_date` of the cycle carrying the held line, that `HELD_AUTH` line becomes `EXCLUDED_HELD` with `hold_reason` `AUTH_ESCALATED` — the pharmacy gives up on the drug rather than delay the whole roll. If the clock date has not yet reached the cycle's start, the line stays `HELD_AUTH` and the cycle keeps waiting. When dropping the line leaves the cycle with no line whose `line_status` is `HELD_AUTH` or `HELD_TOO_SOON` and at least one line `ADJUDICATED`, the cycle's `insurance_status` moves from `EDITS_PENDING` to `CLEARED`, its `total_copay_cents` is recomputed over the `ADJUDICATED` lines and its `version` increments. The request's `version` increments.

**The prescriber's answer.** Responding is available from `SENT` or `ESCALATED`, otherwise `ERR_INVALID_AUTH_STATE`. The body carries `decision`, plus `approved_refills` or `denial_reason` as appropriate. On an approving decision, `approved_refills` must be present, at least 1, at most 12 and no greater than `requested_refills`; on a denying decision `denial_reason` must be present. A violation of either is `ERR_INVALID_APPROVED_DAYS`.

An approval sets `status` `APPROVED` and stores `approved_refills`. Because the request was approved, the prescription moves from `PENDING_AUTHORIZATION` back to `ACTIVE` with both `refills_authorized` and `refills_remaining` raised by `approved_refills`. Because refills exist again, every line of that prescription whose `line_status` is `HELD_AUTH` becomes `ADJUDICATED`: its `copay_cents` is computed exactly as a first-pass adjudication would compute it, and the dispense is stamped onto the prescription in the same order — `prior_last_dispensed_date` and `prior_last_dispensed_days_supply` preserved first, then `last_dispensed_date` and `last_dispensed_days_supply` advanced, `days_dispensed_total` raised by `days_supply_filled`, `refills_remaining` reduced by 1 and `refills_consumed` raised by 1. Because a held line resolved, each affected cycle recomputes `total_copay_cents` and, when no `HELD_AUTH` or `HELD_TOO_SOON` line remains and at least one line is `ADJUDICATED`, moves `insurance_status` from `EDITS_PENDING` to `CLEARED`. A line that escalation already moved to `EXCLUDED_HELD` is **not** revived by a late approval.

A denial sets `status` `DENIED` and stores `denial_reason`. The prescription moves from `PENDING_AUTHORIZATION` to `DISCONTINUED`, and every line of that prescription whose `line_status` is `HELD_AUTH` becomes `EXCLUDED_HELD` with `hold_reason` `AUTH_DENIED`. That resolution can also clear the cycle by the same rule, since a denied line is no longer pending. Both branches increment the request's `version`, the prescription's `version` and the `version` of every affected cycle. `APPROVED` and `DENIED` are terminal: neither may be chased, escalated or answered again.

### 3.5. Travel Early-Supply Exceptions

**Requesting.** `Patient` and `PharmacyOperations` may request a travel exception, supplying `patient_id`, `travel_start_date`, `travel_end_date` and `requested_extra_days` (between 1 and 30). Two business checks apply. The trip must be in the future and long enough to justify the request: `travel_start_date` must not be before the clock date, and the number of days from `travel_start_date` through `travel_end_date` counted inclusively must be at least `requested_extra_days`; otherwise `ERR_VACATION_WINDOW_INVALID`. The patient must also have an unused allowance: if `vacation_exceptions_used_this_year` is already greater than or equal to the plan's `vacation_overrides_per_year`, the request fails with `ERR_VACATION_LIMIT_EXCEEDED`. Because `vacation_overrides_per_year` may be zero, a plan can forbid travel exceptions entirely. The new request starts with `status` `SUBMITTED`, `approved_extra_days` null, `waives_refill_too_soon` false, `denial_reason` null, `decided_by_user_id` null, `decided_at` null and `version` 1.

**Deciding.** Deciding is exclusive to `VerifyingPharmacist` and may happen exactly once: `status` must be `SUBMITTED`, otherwise `ERR_INVALID_VACATION_STATE`. The body carries `decision` — one of `APPROVE_PHARMACIST`, `APPROVE_PAYER_OVERRIDE` or `DENY` — plus `approved_extra_days` or `denial_reason` as appropriate. The gates are evaluated in this order:

1. If the decision is either approving kind and the patient has at least one prescription with `status` `ACTIVE` and `is_controlled` true, the decision fails with `ERR_CONTROLLED_SUBSTANCE_NO_OVERRIDE`. An active controlled substance blocks **both** approval branches, not merely the payer branch.
2. If the decision is `APPROVE_PAYER_OVERRIDE` and the patient's plan has `allows_payer_vacation_override` false, the decision fails with `ERR_PAYER_OVERRIDE_NOT_ALLOWED`.
3. If the decision is either approving kind and `approved_extra_days` is absent, below 1 or greater than `requested_extra_days`, or if the decision is `DENY` and `denial_reason` is absent, the decision fails with `ERR_INVALID_APPROVED_DAYS`.

The two approval branches diverge in exactly one respect. `APPROVE_PHARMACIST` sets `status` `PHARMACIST_APPROVED`, stores `approved_extra_days` and leaves `waives_refill_too_soon` false: the exception extends the day-supply allowance but does **not** waive the payer's refill-too-soon edit. `APPROVE_PAYER_OVERRIDE` sets `status` `PAYER_OVERRIDE_APPROVED`, stores `approved_extra_days` and makes `waives_refill_too_soon` true, which is the only mechanism in this domain that waives the refill-too-soon edit. Both approvals raise the patient's `vacation_exceptions_used_this_year` by 1 and increment the patient's `version`. `DENY` sets `status` `DENIED`, stores `denial_reason`, leaves `approved_extra_days` null and leaves the yearly counter untouched. All three branches stamp `decided_by_user_id` with the caller's `X-User-ID` and `decided_at` with the clock, and increment the request's `version`. All three states are terminal.

### 3.6. The Pouch Bench: Generation, Packing, Imaging, Verification and Rework

**Generating the roll.** Roll generation is exclusive to `PackagingTechnician`. Its gates are evaluated in this order: the cycle's `packaging_status` must be `LINES_ADJUDICATED`, otherwise `ERR_INVALID_CYCLE_STATE`; `insurance_status` must not be `EDITS_PENDING`, otherwise `ERR_CYCLE_NOT_CLEARED`; at least one line must have `line_status` `ADJUDICATED` and `packable_route` `POUCH`, otherwise `ERR_NO_PACKABLE_LINES`; every line whose `line_status` is `ADJUDICATED` must reference a prescription whose `status` is `ACTIVE`, otherwise `ERR_RX_PENDING_AUTHORIZATION`; the segment the new roll would occupy must not collide with a live roll of the same patient under closed-inclusive semantics, otherwise `ERR_REISSUE_SEGMENT_OVERLAP`; and only then, if `insurance_status` is `REJECTED_TOO_SOON`, the request fails with `ERR_REFILL_TOO_SOON`. Because the refill-too-soon block sits last in that order, a cold-chain-only cycle that was also rejected as too soon reports the absence of packable lines rather than the payer rejection.

**Roll geometry.** The contributing lines are exactly those of the cycle whose `line_status` is `ADJUDICATED` and whose `packable_route` is `POUCH`. Cold-chain and non-packable lines never contribute a pouch — they ship loose — so the roll's shape is a function of the pouch-routed subset alone. The set of slots the roll uses is the union of `dose_times` over the contributing lines' prescriptions. One pouch is produced for each distinct pairing of a calendar date with a slot such that at least one contributing line both covers that date, meaning the date is on or after that line's `line_start_date` and strictly before its `line_end_date`, and lists that slot in its prescription's `dose_times`. `PouchRoll.pouch_count` is the number of such pairs, counting only pouches whose `verification_result` is not `VOID`, and the cycle's `roll_pouch_count` is set to that same figure.

Each pouch records its `roll_id`, its `dose_date`, its `dose_slot`, and a 1-based `pouch_index` assigned by ascending `dose_date` and, within a date, by slot in the order `MORNING`, then `NOON`, then `EVENING`, then `BEDTIME`. `contents` holds one object per contributing line covering that pairing, each carrying that line's `prescription_id` and a `quantity` equal to the prescription's `quantity_per_dose`; the objects are ordered by ascending prescription `created_at`. `expected_pill_count` is the sum of the `quantity` values across `contents` and is the count the verification image must match. Each pouch starts with `verification_result` `PENDING` and with `detected_pill_count`, `image_confidence_pct`, `imaged_by_user_id` and `imaged_at` all null.

The roll itself is created with `verification_status` `BUILT`, a stamped human-readable `roll_serial`, `segment_start_date` equal to the earliest `line_start_date` among contributing lines, and `segment_end_date` equal to the latest `line_end_date` among contributing lines moved back by one day — because `segment_end_date` is inclusive, it names the last date for which a pouch exists, whereas `line_end_date` is exclusive. `packed_by_user_id`, `packed_at`, `verified_by_user_id` and `verified_at` are null, `rework_count` is 0 and `mismatch_pouch_count` is 0. The cycle's `packaging_status` moves from `LINES_ADJUDICATED` to `ROLL_GENERATED` and its `version` increments.

**Packing.** Packing is exclusive to `PackagingTechnician`. The roll's `verification_status` must be `BUILT`, otherwise `ERR_INVALID_ROLL_STATE`, and the roll must hold at least one pouch. On success `verification_status` becomes `PACKED`, `packed_by_user_id` is set to the caller's `X-User-ID` and `packed_at` to the clock; the cycle's `packaging_status` moves from `ROLL_GENERATED` to `PACKED`. Both the roll's `version` and the cycle's `version` increment. Recording the packer is what arms the segregation-of-duties control.

**Imaging one pouch.** Both `PackagingTechnician` and `VerifyingPharmacist` may image. The single-pouch route takes `detected_pill_count` and `image_confidence_pct` (0 through 100) and applies three gates in order: the pouch's roll must have `verification_status` `PACKED`, otherwise `ERR_INVALID_ROLL_STATE`; the pouch's `verification_result` must still be `PENDING`, otherwise `ERR_IMAGE_ALREADY_CAPTURED`; and the caller's `X-User-ID` must not equal the roll's `packed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`.

The outcome is derived in a fixed precedence. If `image_confidence_pct` is strictly below 90, `verification_result` becomes `UNREADABLE` regardless of the pill count — a low-confidence read is never accepted as a match even when the count happens to agree. Otherwise, if `detected_pill_count` equals `expected_pill_count`, `verification_result` becomes `MATCH`. Otherwise it becomes `MISMATCH_COUNT`. The submitted `detected_pill_count` and `image_confidence_pct` are stored, `imaged_by_user_id` is set to the caller's `X-User-ID` and `imaged_at` to the clock. The roll's `mismatch_pouch_count` is then recomputed as the number of its pouches whose `verification_result` is `MISMATCH_COUNT` or `UNREADABLE`. Both the pouch's `version` and the roll's `version` increment.

**Imaging the whole roll in one bench pass.** The whole-roll route models a single scanner sweep. Its body carries `image_confidence_pct` for the pass and an optional `overrides` array; each element of `overrides` names a `pouch_index` and carries a `detected_pill_count`, and may carry its own `image_confidence_pct`. Its gates are the roll's `verification_status` being `PACKED`, otherwise `ERR_INVALID_ROLL_STATE`, and the caller not being the packer, otherwise `ERR_SEGREGATION_OF_DUTIES`.

The pass walks every pouch of the roll whose `verification_result` is still `PENDING`, in ascending `pouch_index` order. For each such pouch the effective reading is, by default, a `detected_pill_count` equal to that pouch's `expected_pill_count` and the body's `image_confidence_pct` — the scanner is assumed to have read the pouch correctly. If an element of `overrides` names that pouch's `pouch_index`, that element's `detected_pill_count` is used instead, and its `image_confidence_pct` replaces the body value for that pouch alone when supplied. The effective reading is then resolved into `verification_result` by exactly the same precedence as the single-pouch route: `UNREADABLE` when the effective `image_confidence_pct` is strictly below 90, otherwise `MATCH` when the effective `detected_pill_count` equals `expected_pill_count`, otherwise `MISMATCH_COUNT`. Every pouch touched by the pass has `imaged_by_user_id` set to the caller's `X-User-ID` and `imaged_at` set to the clock; pouches that were already imaged are left completely untouched, including any override element naming them. The roll's `mismatch_pouch_count` is recomputed as before. The roll's `version` increments by 1, and the `version` of each pouch actually imaged by this pass increments by 1.

**Verification.** Verification is exclusive to `VerifyingPharmacist` and is a second-person control. Its gates, in order: the roll's `verification_status` must be `PACKED` and no pouch of the roll may still have `verification_result` `PENDING`, otherwise `ERR_INVALID_ROLL_STATE`; and the caller's `X-User-ID` must not equal `packed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. Both branches stamp `verified_by_user_id` with the caller's `X-User-ID` and `verified_at` with the clock, and increment the roll's `version` and the cycle's `version`.

The branch is chosen by `mismatch_pouch_count`. When it is zero, the roll's `verification_status` becomes `PASSED` — a terminal state — and the cycle's `packaging_status` moves from `PACKED` to `VERIFIED`. When it is one or more, the roll's `verification_status` becomes `FAILED_QUARANTINED` and the cycle's `packaging_status` moves **backwards** from `PACKED` to `ROLL_GENERATED`; in addition a credit memo is issued against the cycle with `reason` `FAILED_VERIFICATION`, `amount_cents` of 500, `status` `ISSUED` and `issued_at` at the clock, and the patient's `credit_balance_cents` rises by that amount as a goodwill gesture.

**Rework.** Rework is exclusive to `VerifyingPharmacist`. The roll's `verification_status` must be `FAILED_QUARANTINED`, otherwise `ERR_INVALID_ROLL_STATE`, and `rework_count` must be below 2, otherwise `ERR_REWORK_LIMIT_REACHED` — a roll may return to the bench at most twice. On success `verification_status` returns to `BUILT`, `rework_count` rises by 1, and `packed_by_user_id`, `packed_at`, `verified_by_user_id` and `verified_at` are all cleared to null, which releases the segregation-of-duties constraint for the next pack attempt. Every pouch of the roll whose `verification_result` is not `VOID` resets to `PENDING` with `detected_pill_count`, `image_confidence_pct`, `imaged_by_user_id` and `imaged_at` cleared to null; a `VOID` pouch is left as it is. `mismatch_pouch_count` returns to 0 and the roll's `version` increments. The cycle's `packaging_status` is already `ROLL_GENERATED` from the failed verification and is not changed again.

### 3.7. Split Shipment, Dispatch, Delivery and Cold-Chain Excursions

A single cycle can require up to three parcels, because three fulfilment routes exist and they cannot travel together: the pouch roll itself, a cold-chain parcel for refrigerated items, and a loose parcel for non-packable items. Staging, dispatch and delivery are all exclusive to `PharmacyOperations`.

**Staging a parcel.** The body carries `shipment_kind` (`POUCH_ROLL`, `COLD_CHAIN` or `NON_PACKABLE_LOOSE`), `carrier_service` (`GROUND`, `TWO_DAY` or `OVERNIGHT`) and an optional `packaging` (`STANDARD`, `INSULATED_GEL` or `INSULATED_DRY_ICE`); when `packaging` is omitted it is `STANDARD`. The gates are evaluated in this order:

1. The cycle's `packaging_status` must permit the requested kind, otherwise `ERR_INVALID_CYCLE_STATE`. A `POUCH_ROLL` parcel may be staged only when `packaging_status` is `VERIFIED` or `SHIPPED`, because the roll must have cleared the bench. A `COLD_CHAIN` or `NON_PACKABLE_LOOSE` parcel may be staged from `LINES_ADJUDICATED`, `ROLL_GENERATED`, `PACKED`, `VERIFIED` or `SHIPPED`, because a loose or cold-chain parcel leaves the building independently of the pouch bench and need not wait for verification.
2. `packaging` must suit the kind, otherwise `ERR_COLD_CHAIN_PACKAGING_INVALID`: a `COLD_CHAIN` parcel may not use `STANDARD` packaging, and a parcel of any other kind may not use `INSULATED_GEL` or `INSULATED_DRY_ICE`.
3. The cycle must actually have freight of that kind and must not already have such a parcel in flight, otherwise `ERR_NO_LINES_FOR_SHIPMENT_KIND`. At least one line with `line_status` `ADJUDICATED` or `PACKED_OUT` must map to the requested kind — `POUCH_ROLL` requires a line whose `packable_route` is `POUCH`, `COLD_CHAIN` requires a `COLD_CHAIN` line, `NON_PACKABLE_LOOSE` requires a `LOOSE_SPLIT` line — and no shipment of that kind may already exist for the cycle with a `status` other than `CANCELLED` or `EXCEPTION_RETURNED`. A cancelled or returned parcel therefore frees the kind to be staged again.
4. For a `COLD_CHAIN` parcel only, no other cold-chain shipment of the same patient whose `status` is neither `CANCELLED` nor `EXCEPTION_RETURNED` may have a `staged_at` whose absolute distance from the clock is under 48 hours, otherwise `ERR_COLD_CHAIN_GAP_VIOLATION`. A separation of exactly 48 hours is permitted.

The new shipment starts with `status` `STAGED`, `staged_at` at the clock, `tracking_number` null, `dispatched_at`, `delivered_at` and `pickup_confirmed_at` null, `cold_chain_excursion_minutes` 0 and `version` 1. `covers_line_ids` holds the identifiers of the cycle's lines whose `packable_route` maps to this `shipment_kind` and whose `line_status` is `ADJUDICATED` or `PACKED_OUT`, ordered by ascending line `created_at`. The cycle's `version` increments.

**Freight cost.** `ship_cost_cents` is stamped at staging as the sum of three independent additive components. The kind contributes 0 cents for `POUCH_ROLL`, 495 cents for `NON_PACKABLE_LOOSE` and 1295 cents for `COLD_CHAIN`. The packaging contributes 0 cents for `STANDARD`, 350 cents for `INSULATED_GEL` and 900 cents for `INSULATED_DRY_ICE`. The service contributes 0 cents for `GROUND`, 600 cents for `TWO_DAY` and 1800 cents for `OVERNIGHT`. No rounding is involved; every component is already a whole number of cents.

**Dispatch.** The shipment's `status` must be `STAGED`, otherwise `ERR_INVALID_SHIPMENT_STATE`. When `shipment_kind` is `POUCH_ROLL`, the cycle's pouch roll must have `verification_status` `PASSED`, otherwise `ERR_ROLL_NOT_VERIFIED`. On success `status` becomes `IN_TRANSIT`, a `tracking_number` is stamped and `dispatched_at` is set to the clock.

Dispatch also carries the cycle's financial close, but only when it is the dispatch that completes the cycle. The cycle's required kinds are derived from its lines whose `line_status` is `ADJUDICATED`: `POUCH_ROLL` is required if any such line has `packable_route` `POUCH`, `COLD_CHAIN` if any has `COLD_CHAIN`, and `NON_PACKABLE_LOOSE` if any has `LOOSE_SPLIT`. When, after this dispatch, every required kind has a shipment whose `status` is `IN_TRANSIT`, `DELIVERED` or `PICKED_UP`, the cycle's `packaging_status` moves from `VERIFIED` to `SHIPPED` and the copay is finalised:

- `final_copay_cents` is computed by summing the **unrounded** per-line amounts over the lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT` — each amount being the tier's per-day rate multiplied by the line's `days_supply_filled`, multiplied by one hundred minus `coinsurance_pct`, divided by one hundred — and rounding that single sum half-up to whole cents. This sum-then-round-once discipline is what distinguishes the final figure from the provisional `total_copay_cents`, which rounded each line first.
- `rounding_delta_cents` is `total_copay_cents` minus `final_copay_cents`. The delta may be positive, zero or negative.
- When `rounding_delta_cents` is at least 1 cent, a credit memo is issued with `reason` `ROUNDING_TRUEUP`, `amount_cents` equal to `rounding_delta_cents` and `status` `ISSUED`, and the patient's `credit_balance_cents` rises by that amount. When `rounding_delta_cents` is zero or negative, no memo is issued and no additional charge is raised — the patient is never billed for a rounding difference in the pharmacy's favour.
- Every line of the cycle whose `line_status` is `ADJUDICATED` becomes `PACKED_OUT`.

The shipment's `version` and the cycle's `version` increment. A dispatch that does not complete the cycle changes only the shipment and leaves the cycle at `VERIFIED` with `final_copay_cents` and `rounding_delta_cents` still null.

**Delivery, and the cold-chain branch.** Recording delivery accepts an optional `cold_chain_excursion_minutes`, a count of zero or more minutes the parcel spent outside its validated temperature range; when omitted it is 0. The shipment's `status` must be `IN_TRANSIT`, otherwise `ERR_INVALID_SHIPMENT_STATE`. The reported figure is stored on the shipment in both branches, and `delivered_at` is set to the clock in both branches.

The ordinary branch applies to any parcel whose `shipment_kind` is not `COLD_CHAIN`, and to a cold-chain parcel whose `cold_chain_excursion_minutes` is at most 120: `status` becomes `DELIVERED` and nothing else changes. The exception branch applies only to a `COLD_CHAIN` parcel whose `cold_chain_excursion_minutes` is strictly greater than 120 — the drug is no longer safe, so the parcel is returned and the entire dispense is unwound:

- `status` becomes `EXCEPTION_RETURNED`.
- Every line named in `covers_line_ids` becomes `CREDITED`.
- Because those lines were credited, each one's prescription reverses its dispense exactly: `days_dispensed_total` falls by that line's `days_supply_filled`, `refills_remaining` rises by 1, `refills_consumed` falls by 1, and `last_dispensed_date` and `last_dispensed_days_supply` are restored verbatim from `prior_last_dispensed_date` and `prior_last_dispensed_days_supply`. The refills invariant therefore holds again, and a subsequent cycle adjudicates against the pre-dispense history rather than against a fill the patient never received.
- A credit memo is issued with `reason` `COLD_CHAIN_EXCURSION`, `amount_cents` equal to the sum of `copay_cents` over the credited lines and `status` `ISSUED`, and the patient's `credit_balance_cents` rises by that amount.
- The cycle's `total_copay_cents` is recomputed over its remaining lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`; credited lines no longer contribute.
- An adherence event is appended with `event_type` `DELIVERY_EXCEPTION` and `source` `SYSTEM_SCAN`, attributed to the cycle through `cycle_id`.

The shipment's `version` increments in both branches, as does the `version` of every prescription and cycle touched by the exception branch. `EXCEPTION_RETURNED` is terminal, and it frees the `COLD_CHAIN` kind for a fresh parcel — subject again to the 48-hour separation buffer.

### 3.8. Pickup, Adherence Gap Detection and Auto-Ship Posture

**Confirming pickup.** Confirming pickup is the patient's exclusive act: no staff role may perform it. The shipment's `status` must be `DELIVERED`, otherwise `ERR_INVALID_SHIPMENT_STATE`, and the caller's `X-User-ID` must be the patient who owns the shipment's cycle. On success `status` becomes `PICKED_UP`, `pickup_confirmed_at` is set to the clock, and an adherence event is appended with `event_type` `PICKUP_CONFIRMED` and `source` `PATIENT_REPORTED`. The patient's `consecutive_missed_pickups` is reset to 0 — a confirmed collection breaks the streak entirely rather than decrementing it. When every shipment of the cycle has reached a terminal `status` — `PICKED_UP`, `PICKUP_MISSED`, `EXCEPTION_RETURNED` or `CANCELLED` — the cycle's `packaging_status` moves from `SHIPPED` to `CLOSED`. The shipment's `version` and the cycle's `version` increment.

**Reporting dose events.** `Patient` and `PharmacyOperations` may append a batch of dose events. The body carries `cycle_id`, the cycle the events are attributed to, and `events`, a non-empty array. Each element carries `event_type` — `POUCH_TAKEN` or `POUCH_MISSED` — together with `occurred_at`, `dose_slot` and `pouch_index`. `occurred_at` must not be after the clock. One immutable adherence event is created per element, each carrying only `id` and `created_at` beyond its own payload; `source` is `PATIENT_REPORTED` when `X-User-Role` is `Patient` and `SYSTEM_SCAN` otherwise. Events are never edited or deleted once written.

**The rolling adherence score.** After the batch is appended, the patient's `adherence_score_pct` is recomputed. The window is half-open: it begins at the clock moved back by 28 days, inclusive, and ends at the clock, exclusive. The eligible events are those whose `cycle_id` belongs to a fill cycle of this patient, whose `event_type` is `POUCH_TAKEN` or `POUCH_MISSED`, and whose `occurred_at` falls inside that window; pickup and delivery events never enter the score. Count the taken events and the missed events. When the two counts sum to zero, `adherence_score_pct` is 100. Otherwise it is one hundred multiplied by the taken count, divided by the sum of the two counts, floored to a whole percent.

**The cycle-scoped score.** A second, read-only score is derivable from the same event stream and it deliberately disagrees with the first. Its denominator is the number of pouches across the patient's rolls whose `dose_date` is strictly before the clock date and whose `verification_result` is not `VOID` — that is, every pouch whose dose date has already passed, whether or not the patient reported anything about it. When that count is zero the cycle-scoped score is 100; otherwise it is one hundred multiplied by the same taken count, divided by that expected count, floored to a whole percent. The rolling score ignores elapsed pouches that produced no event at all, while the cycle-scoped score counts them against the patient, so the cycle-scoped figure is the more pessimistic of the two whenever a dose went unreported. Only the rolling score is written to `adherence_score_pct` and only the rolling score can pause auto-ship.

**The adherence summary read.** A computed read exposes both variants side by side for one patient, returning `patient_id`, `rolling_28_day_score_pct`, `cycle_scoped_score_pct`, `taken_count`, `missed_count`, `expected_pouch_count`, `consecutive_missed_pickups` and `autoship_status`. `taken_count` and `missed_count` are the two window counts, and `expected_pouch_count` is the cycle-scoped denominator. This read mutates nothing.

**The pause gate.** After every dose-event batch and after every adherence review, the auto-ship gate is evaluated, and the score gate is evaluated **first**. If `adherence_score_pct` is strictly below 80, the patient's `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `ADHERENCE_GAP`. Otherwise, if `consecutive_missed_pickups` is greater than or equal to 2, `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `MISSED_PICKUPS`. A score exactly equal to 80 does not pause. When both conditions hold, `pause_reason` is `ADHERENCE_GAP`, because the score gate was reached first. When auto-ship pauses this way, every fill cycle of the patient whose `packaging_status` is `DRAFT` becomes `CANCELLED` and every cycle line of those cancelled cycles becomes `EXCLUDED_HELD`, with `hold_reason` left null because no per-line edit failed. The patient's `version` increments, as does the `version` of every cancelled cycle and excluded line.

**The adherence review sweep.** The review is exclusive to `PharmacyOperations` and takes no body. It sweeps the patient's parcels for an expired pickup grace period: every shipment of the patient whose `status` is `DELIVERED` and whose `delivered_at` advanced by 5 days is at or before the clock becomes `PICKUP_MISSED`, and each such sweep appends an adherence event with `event_type` `PICKUP_MISSED` and `source` `SYSTEM_SCAN`. The patient's `consecutive_missed_pickups` rises by the number of parcels swept in this run. Then `adherence_score_pct` is recomputed and the same pause gate is evaluated, with the same cascade into `DRAFT` cycles and their lines. The patient's `version` increments, as does the `version` of every swept shipment.

**Changing auto-ship posture.** `PharmacyOperations` and `Patient` may change posture by supplying `action`, one of three values:

- `PAUSE` moves `autoship_status` from `ACTIVE` to `PAUSED_PATIENT` with `pause_reason` `PATIENT_REQUEST`, and every fill cycle of the patient whose `packaging_status` is `DRAFT` becomes `CANCELLED`.
- `RESUME` moves `autoship_status` from `PAUSED_ADHERENCE` or `PAUSED_PATIENT` back to `ACTIVE`, sets `pause_reason` to null and resets `consecutive_missed_pickups` to 0. It does not revive the cycles that the pause cancelled, and it does not recompute `adherence_score_pct` — a resumed patient whose rolling score is still below 80 will pause again on the next dose-event batch or review.
- `CANCEL` moves `autoship_status` to `CANCELLED`, the terminal posture, with `pause_reason` `PATIENT_REQUEST`. Every fill cycle of the patient whose `packaging_status` is `DRAFT` becomes `CANCELLED`, and — uniquely to this action — every credit memo of the patient whose `status` is `ISSUED` becomes `VOIDED` and `credit_balance_cents` is set to 0, because an unredeemed credit has no future fill to land on.

Every action increments the patient's `version`, plus the `version` of every cascaded cycle, line and memo. Note the asymmetry between the two pause postures: `PAUSED_PATIENT` and `PAUSED_ADHERENCE` both block cycle creation, adjudication and reissue through `ERR_AUTOSHIP_PAUSED`, but only `PAUSED_PATIENT` is reachable by the patient's own request, and only `PAUSED_ADHERENCE` is reachable by a breached gate. Synchronization remains available while `autoship_status` is `PAUSED_PATIENT` but not while it is `PAUSED_ADHERENCE` or `CANCELLED`.

### 3.9. Mid-Cycle Regimen Change and Partial Reissue

**Issuing a regimen change.** A regimen change is exclusive to `Prescriber` and is the disruption this whole subsystem exists to absorb: the prescriber changes a drug while a roll built on the old regimen is already on the bench or in the building. The body carries `new_drug_name`, `new_form`, `new_copay_tier`, `new_dose_times`, `new_quantity_per_dose` and `expected_prescription_version` as required fields, and may carry `new_ndc`, `new_strength`, `new_days_supply_written` and `change_reason`. The stale-version check comes first: if `expected_prescription_version` does not equal the prescription's current `version`, the request fails with `ERR_STALE_PRESCRIPTION_VERSION`. Only then is state checked: the prescription's `status` must be `ACTIVE`, otherwise `ERR_INVALID_PRESCRIPTION_STATE`.

The addressed prescription moves from `ACTIVE` to the terminal `SUPERSEDED`, and a successor prescription is created with `status` `ACTIVE` and `supersedes_rx_id` pointing at the addressed prescription's `id`. The successor takes `drug_name`, `form`, `copay_tier`, `dose_times` and `quantity_per_dose` from the `new_` fields, takes `ndc`, `strength` and `days_supply_written` from the corresponding `new_` fields when supplied and from the superseded prescription otherwise, carries `refills_remaining` and `refills_consumed` forward unchanged, and recomputes `packable` from `new_form` together with the inherited `refrigerated` flag. **The response body is the new successor prescription, not the superseded one.**

Three cascades follow, in order. Because the prescription was superseded, every cycle line referencing it on a cycle whose `packaging_status` is `DRAFT`, `LINES_ADJUDICATED`, `ROLL_GENERATED`, `PACKED` or `VERIFIED` becomes `SUPERSEDED_PENDING_REISSUE` with `hold_reason` `REGIMEN_CHANGE`; lines on a cycle that has already reached `SHIPPED`, `CLOSED` or `CANCELLED` are left alone, because that medication has already left the building. Because at least one line was superseded, each affected cycle sets `reissue_required` to true, and a cycle whose `packaging_status` is `PACKED` or `VERIFIED` reverts to `ROLL_GENERATED` — the roll must be rebuilt, and a reverted roll is re-generated rather than re-verified. Because the cycle reverted, every shipment of that cycle whose `status` is `STAGED` and whose `shipment_kind` is `POUCH_ROLL` becomes `CANCELLED`; cold-chain and loose parcels are untouched, since they never carried the changed drug's pouches. The superseded prescription's `version` increments, and so does the `version` of every affected cycle, line and shipment.

**Reissuing the untaken tail.** Partial reissue is exclusive to `PharmacyOperations`. The body carries `effective_date` (the date from which the new regimen takes over), `replacement_prescription_ids` (the prescriptions the new partial cycle will fill) and `expected_cycle_version`. Its gates are evaluated in this order: the stale-version check on `expected_cycle_version`, otherwise `ERR_STALE_CYCLE_VERSION`; the patient's `autoship_status` must be `ACTIVE`, otherwise `ERR_AUTOSHIP_PAUSED`; the cycle's `packaging_status` must be `ROLL_GENERATED`, `PACKED` or `VERIFIED`, otherwise `ERR_INVALID_CYCLE_STATE`; `effective_date` must be strictly after the cycle's `cycle_start_date` and strictly before its `cycle_end_date`, otherwise `ERR_REISSUE_DATE_OUT_OF_WINDOW`; and the cycle must have something to reissue — at least one line with `line_status` `SUPERSEDED_PENDING_REISSUE`, or at least one `ADJUDICATED` line whose prescription is named in `replacement_prescription_ids` — otherwise `ERR_NOTHING_TO_REISSUE`.

**The credit computation.** The credit is computed in exactly four ordered steps, and the order matters because the fee tier is read off the value the cycle *retains*, which the credit itself reduces.

*Step one — the gross credit, rounded per line.* The consumed portion of the cycle is `used_days`, the number of days from the cycle's `cycle_start_date` to `effective_date`. For each line being reissued, its unused portion is that line's `days_supply_filled` minus `used_days`. The line's credit is the line's `copay_cents` multiplied by its unused days, divided by its `days_supply_filled`, rounded half-up to whole cents. The gross credit is the sum of those per-line credits over the lines being reissued — the lines whose `line_status` is `SUPERSEDED_PENDING_REISSUE`, together with the `ADJUDICATED` lines whose prescription is named in `replacement_prescription_ids`.

*Step two — the retained basis.* Subtract the gross credit from the cycle's `total_copay_cents`. The result is the value the cycle retains, and it is this number, not `total_copay_cents`, that selects the fee tier.

*Step three — the fee tier.* If the retained basis is at least 5000 cents, `reissue_fee_cents` is 0 — the fee is waived on a large retained cycle. Otherwise, if the retained basis is at least 2000 cents, `reissue_fee_cents` is 250. Otherwise `reissue_fee_cents` is 500. The comparisons are inclusive at each boundary, so a retained basis of exactly 5000 waives the fee and a retained basis of exactly 2000 takes the reduced fee.

*Step four — the net credit.* The credit memo's `amount_cents` is the gross credit minus `reissue_fee_cents`, floored at zero so it is never negative. `reissue_fee_cents` is stamped on the **original** cycle, and the memo is issued with `reason` `PARTIAL_REISSUE`, `cycle_id` naming the original cycle, `status` `ISSUED` and `issued_at` at the clock; the patient's `credit_balance_cents` rises by `amount_cents`. Money is conserved: the original `total_copay_cents` equals the retained basis plus the net credit plus the fee.

**Trimming the original cycle.** Each reissued line becomes `REISSUED`, retains only the consumed portion — its `copay_cents` reduced by its own line credit, its `days_supply_filled` set to `used_days`, and its `line_end_date` set to `effective_date` — and the original cycle's `total_copay_cents` is recomputed over the lines it retains. Each reissued line's prescription is adjusted to reflect what was actually consumed rather than what was dispensed: `last_dispensed_days_supply` is reset to `used_days` and `days_dispensed_total` is reduced by that line's unused days, so the successor cycle's refill-too-soon and day-supply edits measure against real consumption. The pouch roll's `segment_end_date` is truncated to the day before `effective_date`, since no pouch beyond that date survives.

**The successor cycle.** A new fill cycle is created with `is_partial_reissue` true, `reissue_of_cycle_id` naming the original cycle, `cycle_start_date` equal to `effective_date`, `day_supply_days` equal to the number of days from `effective_date` to the original cycle's `cycle_end_date`, `packaging_status` `DRAFT`, `insurance_status` `NOT_ADJUDICATED`, and one `PLANNED` cycle line per prescription named in `replacement_prescription_ids`. Because `is_partial_reissue` is true, this child cycle does not participate in the half-open cycle-window overlap test, so it may legitimately sit inside the original cycle's window. The original cycle's `version` increments, and the successor cycle is created at `version` 1. **The response body is the new partial-reissue fill cycle, not the original.** The successor then follows the ordinary path: it must be adjudicated, rolled, packed, imaged, verified, shipped and collected like any other cycle, and the credit issued against the original cycle will be consumed the next time a cycle of that patient adjudicates.

## 4. Endpoint Definitions

Every path below is rooted at the `/pharmacy` prefix. Read operations return HTTP 200. Write operations that bring a new resource into existence return HTTP 201 with that resource in `data`; write operations that only advance an existing resource return HTTP 200 with the updated resource in `data`. Two write operations return a resource other than the one addressed in the path: the regimen change returns the newly minted successor prescription, and the partial reissue returns the newly created partial-reissue fill cycle. The logical-clock setter returns HTTP 200 with an object carrying `current_utc`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| GET | `/pharmacy/insurance-plans/{id}` | Retrieve one payer plan with its edit thresholds and per-day copay rates. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist` |
| GET | `/pharmacy/patients` | List patients, filterable by payer plan, auto-ship posture and synchronization state. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist` |
| GET | `/pharmacy/patients/{id}` | Retrieve one patient with their synchronization, auto-ship, adherence and credit figures. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician`, `Patient` |
| GET | `/pharmacy/patients/{id}/adherence-summary` | Computed read exposing both adherence variants side by side; only the rolling score can pause auto-ship. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Patient` |
| GET | `/pharmacy/prescriptions` | List prescriptions; the successor-chain filter resolves prescriptions minted by regimen changes. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Prescriber`, `Patient` |
| GET | `/pharmacy/prescriptions/{id}` | Retrieve one prescription with its refill, dispense-history and packability state. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Prescriber`, `Patient` |
| GET | `/pharmacy/fill-cycles` | List fill cycles, filterable by patient, reissue parent, travel exception and either state dimension. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician`, `Patient` |
| GET | `/pharmacy/fill-cycles/{id}` | Retrieve one fill cycle with both state dimensions and its copay and credit figures. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician`, `Patient` |
| GET | `/pharmacy/cycle-lines` | List claim lines, filterable by cycle, prescription and line state. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician` |
| GET | `/pharmacy/cycle-lines/{id}` | Retrieve one claim line with its routing, day-supply and copay figures. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician` |
| GET | `/pharmacy/pouch-rolls` | List pouch rolls, filterable by cycle and verification state. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician` |
| GET | `/pharmacy/pouch-rolls/{id}` | Retrieve one pouch roll with its segment, pack and verification identities. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician` |
| GET | `/pharmacy/pouches` | List pouches in roll sequence, filterable by roll, imaging outcome and dose slot. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician` |
| GET | `/pharmacy/pouches/{id}` | Retrieve one pouch with its contents, expected count and imaging result. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician` |
| GET | `/pharmacy/shipments` | List parcels, filterable by cycle, parcel kind and parcel state. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician`, `Patient` |
| GET | `/pharmacy/shipments/{id}` | Retrieve one parcel with its covered lines, freight cost and transit timestamps. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician`, `Patient` |
| GET | `/pharmacy/refill-authorizations` | List refill authorization requests, filterable by prescription and chase state. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Prescriber` |
| GET | `/pharmacy/refill-authorizations/{id}` | Retrieve one refill authorization request with its chase and escalation counters. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Prescriber` |
| GET | `/pharmacy/vacation-exceptions` | List travel early-supply exception requests, filterable by patient and decision state. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Patient` |
| GET | `/pharmacy/vacation-exceptions/{id}` | Retrieve one travel exception with its approved days and waiver flag. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Patient` |
| GET | `/pharmacy/credit-memos` | List credit memos, filterable by patient, issuing cycle, consuming cycle, reason and state. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Patient` |
| GET | `/pharmacy/credit-memos/{id}` | Retrieve one credit memo with its amount, reason and application state. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Patient` |
| GET | `/pharmacy/adherence-events` | List immutable adherence events, filterable by cycle, event type and source. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Patient` |
| GET | `/pharmacy/adherence-events/{id}` | Retrieve one immutable adherence event. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Patient` |
| GET | `/pharmacy/fill-cycles/{id}/adherence-events` | Sub-resource read of one cycle's adherence event stream in occurrence order. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `Patient` |
| POST | `/pharmacy/insurance-plans` | Register a payer plan with its edit thresholds and per-day copay rates. | `PlatformAdmin` |
| POST | `/pharmacy/patients` | Enrol a patient against a payer plan; the patient starts unsynchronized. | `PlatformAdmin`, `PharmacyOperations` |
| POST | `/pharmacy/prescriptions` | Record a prescription; packability is computed and may not be supplied. | `Prescriber`, `PharmacyOperations` |
| POST | `/pharmacy/patients/{id}/synchronize` | Pin the patient's common fill cycle anchor and alignment policy, sweeping expired prescriptions. | `PharmacyOperations` |
| POST | `/pharmacy/patients/{id}/autoship` | Pause, resume or cancel auto-ship for the patient. | `PharmacyOperations`, `Patient` |
| POST | `/pharmacy/patients/{id}/dose-events` | Append an immutable batch of pouch-level adherence events and re-evaluate the pause gate. | `Patient`, `PharmacyOperations` |
| POST | `/pharmacy/patients/{id}/adherence-review` | Sweep delivered parcels for expired pickup grace and re-evaluate the pause gate. | `PharmacyOperations` |
| POST | `/pharmacy/fill-cycles` | Open a fill cycle for a synchronized patient and stage one planned line per active prescription. | `PharmacyOperations` |
| POST | `/pharmacy/fill-cycles/{id}/adjudicate` | Run the payer edits over every planned line: refill-too-soon, day supply, authorization, routing and copay. | `VerifyingPharmacist` |
| POST | `/pharmacy/fill-cycles/{id}/generate-roll` | Build the dose-time pouch roll for the cycle's pouch-routed lines. | `PackagingTechnician` |
| POST | `/pharmacy/pouch-rolls/{id}/pack` | Claim the roll as packed by the calling technician, pinning the identity barred from verifying it. | `PackagingTechnician` |
| POST | `/pharmacy/pouches/{id}/verification-image` | Record the pack-verification image for one pouch. | `PackagingTechnician`, `VerifyingPharmacist` |
| POST | `/pharmacy/pouch-rolls/{id}/verification-images` | One bench-scanner pass over the whole roll, with per-pouch overrides. | `PackagingTechnician`, `VerifyingPharmacist` |
| POST | `/pharmacy/pouch-rolls/{id}/verify` | Second-person verification of a fully imaged roll; branches on the mismatch count. | `VerifyingPharmacist` |
| POST | `/pharmacy/pouch-rolls/{id}/rework` | Return a quarantined roll to the bench for repacking. | `VerifyingPharmacist` |
| POST | `/pharmacy/fill-cycles/{id}/shipments` | Stage one parcel of the cycle's split shipment and price its freight. | `PharmacyOperations` |
| POST | `/pharmacy/shipments/{id}/dispatch` | Hand the parcel to the carrier; the completing dispatch finalises the cycle copay. | `PharmacyOperations` |
| POST | `/pharmacy/shipments/{id}/deliver` | Record carrier delivery, diverting a cold-chain excursion to a full reversal. | `PharmacyOperations` |
| POST | `/pharmacy/shipments/{id}/confirm-pickup` | Patient-only confirmation that the parcel was collected. | `Patient` |
| POST | `/pharmacy/refill-authorizations` | Open a refill authorization chase against the prescriber. | `PharmacyOperations` |
| POST | `/pharmacy/refill-authorizations/{id}/chase` | Record prescriber silence or re-send the request, depending on the current state. | `PharmacyOperations` |
| POST | `/pharmacy/refill-authorizations/{id}/escalate` | Escalate an exhausted chase and conditionally drop the held line. | `PharmacyOperations` |
| POST | `/pharmacy/refill-authorizations/{id}/respond` | Prescriber decision; approval restores refills and revives the held line. | `Prescriber` |
| POST | `/pharmacy/vacation-exceptions` | Request a travel early-supply exception for a future trip. | `Patient`, `PharmacyOperations` |
| POST | `/pharmacy/vacation-exceptions/{id}/decide` | Decide the travel exception; only the payer-override branch waives the refill-too-soon edit. | `VerifyingPharmacist` |
| POST | `/pharmacy/prescriptions/{id}/regimen-change` | Supersede the prescription, mint a successor and unwind every roll built on the old regimen. | `Prescriber` |
| POST | `/pharmacy/fill-cycles/{id}/reissue` | Reissue the untaken tail as a new partial cycle and credit the unused portion less the fee. | `PharmacyOperations` |
| POST | `/pharmacy/_clock/set_current_utc` | Test-only logical clock setter; mutates no business entity and requires no authentication. | `PlatformAdmin`, `PharmacyOperations`, `VerifyingPharmacist`, `PackagingTechnician`, `Prescriber`, `Patient` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PATIENT_SCOPE_VIOLATION` | 403 |
| `ERR_INSURANCE_PLAN_NOT_FOUND` | 404 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 |
| `ERR_FILL_CYCLE_NOT_FOUND` | 404 |
| `ERR_CYCLE_LINE_NOT_FOUND` | 404 |
| `ERR_POUCH_ROLL_NOT_FOUND` | 404 |
| `ERR_POUCH_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_REFILL_AUTHORIZATION_NOT_FOUND` | 404 |
| `ERR_VACATION_EXCEPTION_NOT_FOUND` | 404 |
| `ERR_CREDIT_MEMO_NOT_FOUND` | 404 |
| `ERR_ADHERENCE_EVENT_NOT_FOUND` | 404 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_STALE_PRESCRIPTION_VERSION` | 412 |
| `ERR_PATIENT_NOT_SYNCHRONIZED` | 409 |
| `ERR_AUTOSHIP_PAUSED` | 409 |
| `ERR_INVALID_CYCLE_STATE` | 409 |
| `ERR_CYCLE_NOT_CLEARED` | 409 |
| `ERR_INVALID_ROLL_STATE` | 409 |
| `ERR_IMAGE_ALREADY_CAPTURED` | 409 |
| `ERR_INVALID_SHIPMENT_STATE` | 409 |
| `ERR_INVALID_AUTH_STATE` | 409 |
| `ERR_INVALID_VACATION_STATE` | 409 |
| `ERR_INVALID_PRESCRIPTION_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_CONTROLLED_SUBSTANCE_NO_OVERRIDE` | 422 |
| `ERR_COLD_CHAIN_NOT_PACKABLE` | 422 |
| `ERR_COLD_CHAIN_PACKAGING_INVALID` | 422 |
| `ERR_NON_PACKABLE_IN_POUCH_ROUTE` | 422 |
| `ERR_NO_PACKABLE_LINES` | 422 |
| `ERR_NO_LINES_FOR_SHIPMENT_KIND` | 422 |
| `ERR_RX_PENDING_AUTHORIZATION` | 409 |
| `ERR_ROLL_NOT_VERIFIED` | 409 |
| `ERR_NO_APPROVED_VACATION_EXCEPTION` | 422 |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 |
| `ERR_REISSUE_SEGMENT_OVERLAP` | 409 |
| `ERR_COLD_CHAIN_GAP_VIOLATION` | 409 |
| `ERR_VACATION_WINDOW_INVALID` | 422 |
| `ERR_CHASE_TOO_EARLY` | 409 |
| `ERR_REISSUE_DATE_OUT_OF_WINDOW` | 422 |
| `ERR_CHASE_LIMIT_REACHED` | 409 |
| `ERR_ESCALATION_PREMATURE` | 409 |
| `ERR_REWORK_LIMIT_REACHED` | 409 |
| `ERR_DAY_SUPPLY_EXCEEDS_ALLOWANCE` | 422 |
| `ERR_VACATION_LIMIT_EXCEEDED` | 422 |
| `ERR_PAYER_OVERRIDE_NOT_ALLOWED` | 422 |
| `ERR_INVALID_APPROVED_DAYS` | 422 |
| `ERR_DUPLICATE_AUTH_REQUEST` | 409 |
| `ERR_INVALID_ANCHOR_DAY` | 422 |
| `ERR_NO_ACTIVE_PRESCRIPTIONS` | 422 |
| `ERR_REFILL_TOO_SOON` | 409 |
| `ERR_NOTHING_TO_REISSUE` | 422 |






