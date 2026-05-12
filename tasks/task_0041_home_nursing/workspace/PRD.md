# Home Nursing API — Product Requirements Document

## 1. Introduction

Home nursing service delivered to a patient's residence sits at the intersection of three failure-sensitive concerns: clinical qualification, on-the-ground execution evidence, and downstream financial settlement. Patients booking an IV infusion or wound-care visit are entrusting a stranger with care that, even when straightforward, carries regulatory weight — the nurse must be currently licensed, currently employed by an affiliated hospital, currently trained on the relevant skill, and currently within radius of the patient's address. None of these "currently" conditions can be answered by a static profile lookup; each requires a lifecycle apparatus that admits and removes nurses on the basis of training records, periodic re-certification, identity-verification handshakes, and disqualification events.

This document specifies the back-office API that drives that apparatus end-to-end. It covers the certification workflow that keeps a nurse on the platform; the patient-side ordering flow including catalog, eligibility review, and prepaid packages; the matching and dispatch engine that selects a single nurse for a given order, with re-dispatch on rejection or expiry; the on-site service record (check-in via GPS and face verification, checklist, vital signs, medications, evidence, abnormal events); medical-waste registration and qualified-disposal handover; fee settlement with distance and time-of-day surcharges, package credits, refunds, tax, and nurse revenue share; complaint submission and multi-stage resolution with rating and compensation impact; periodic payout batches; and the event-driven hooks that synchronize this platform with external payment, identity-verification, IM, and medical-waste-disposal systems. The scope is the platform's own state-machine surface — the integrations are modeled as event ingress/egress, not as RPC dependencies.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two case-sensitive headers identifying the caller: `X-User-ID` (the unique identifier of the calling principal) and `X-User-Role` (one of the four role names enumerated below). When either header is missing or syntactically malformed, the server rejects the request with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` at HTTP 400. When the headers are well-formed but the role is not authorized for the requested operation per the §1.7 RBAC contract, the server returns `ERR_INSUFFICIENT_PERMISSIONS` at HTTP 403.

Four roles are defined, and each role name must be spelled exactly as written:

- `Patient` — an end user who books and consumes service.
- `Nurse` — a credentialed nursing professional who accepts and executes dispatched orders.
- `ComplianceOfficer` — the back-office operator who reviews certifications, eligibility, refunds, and complaints.
- `PlatformAdmin` — the operational super-user managing the service-item catalog, packages, payout batches, and the test hooks.

Identity binding differs by role. When `X-User-Role` is `Nurse`, the value of `X-User-ID` is the `id` of the acting `Nurse` row; ownership checks on any resource that references a nurse — most importantly `Dispatch.nurse_id`, `ServiceRecord.nurse_id`, and the assigned-nurse view of `Order` — compare the resource's foreign-key field directly to `X-User-ID`. When `X-User-Role` is `Patient`, `X-User-ID` is treated as an opaque patient identifier; it is not bound to a persisted entity row, but the server stores it on `Order.patient_id` at order creation, on `Package.patient_id` at package creation, and on `Complaint.patient_id` (copied through from the subject order). Subsequent ownership checks for patient-scoped reads compare these stored `patient_id` values against the caller's `X-User-ID`. When `X-User-Role` is `ComplianceOfficer` or `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it on `AuditLog.actor_id` alongside `AuditLog.actor_role` for audit purposes, but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, with a minimum of 1 and a maximum of 100; values outside these bounds are rejected with `ERR_INVALID_REQUEST`. The default `offset` is 0 and it must be a non-negative integer. List responses are always ordered by the resource's `created_at` ascending (oldest first); for entities without an `updated_at`/`version` pair, `created_at` remains the canonical ordering key.

The pagination block in the success envelope's `meta` exposes four fields for list endpoints: the echoed `limit` and `offset`, the total matching count `total_count`, and a boolean `has_more` set to true when more rows exist beyond the current page.

### 2.4. Common Resource Properties and Optimistic Concurrency

Most resources carry the four common system fields: `id` (a server-minted UUID with no type prefix), `created_at` (an ISO 8601 UTC timestamp with three fractional digits, set once at creation), `updated_at` (the same format, refreshed on every mutation), and `version` (a monotonically increasing integer that begins at 1 and is incremented by exactly 1 on every successful mutation). The five entities covered by this rule are `Nurse`, `ServiceItem`, `Order`, `ServiceRecord`, `Package`, `Settlement`, and `Complaint`.

A second group of entities models append-only or system-generated history that is never edited in place. Every `CertificationRecord`, `Dispatch`, `WasteEntry`, `AuditLog`, and `PayoutBatch` carries only the `id` and `created_at` fields — neither `updated_at` nor `version` is present on these entities. State changes that affect them (for example, a `Dispatch` flipping from `OFFERED` to `ACCEPTED`, or a `WasteEntry` advancing from `REGISTERED` through `HANDED_OVER` to `ARCHIVED`) are still recorded by mutating the row's `status` field, but they do not bump a `version` counter or refresh an `updated_at` timestamp because those columns do not exist on these tables.

Optimistic concurrency control applies to mutations on the version-bearing entities. Any non-idempotent endpoint that updates such a resource accepts an optional `version` field in the request body. When `version` is supplied, the server compares it to the current row's `version`; on mismatch, the request is rejected with `ERR_VERSION_CONFLICT` at HTTP 409 and no state changes. When `version` is omitted, the server skips this check and applies the mutation if all other validations pass — clients that do not require lost-update protection may simply not send the field.

### 2.5. Validation Order and the Header-First Funnel

Validations are evaluated in a fixed priority order, and the first failure terminates request processing. The order is, from highest to lowest priority: (1) header authentication — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role authorization — `ERR_INSUFFICIENT_PERMISSIONS`; (3) path-resource existence, evaluated left to right along the URL hierarchy so that a request like a waste-entry update on `{orderId}/waste-entries/{wasteId}` first verifies the order, then the waste entry — surfacing `ERR_ORDER_NOT_FOUND`, `ERR_NURSE_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_WASTE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or `ERR_PACKAGE_NOT_FOUND` as appropriate; (4) state-machine precondition — `ERR_INVALID_STATE` when the subject is not in a state from which the requested transition is legal; (5) cross-entity referential integrity — `ERR_RESOURCE_LINK_INVALID`; and only thereafter the business-rule layer (medical-doc requirement, certification, geofencing, face verification, checklist completeness, waste archiving, refund window, compensation cap, idempotency, payout-batch exclusivity, and OCC). General request-body shape problems (missing required fields, type mismatches, malformed enums) surface as `ERR_INVALID_REQUEST` at HTTP 400 and are evaluated alongside or immediately after the header check, before any database lookup.

This ordering is itself observable. For example, when a `Patient` calls confirm-completion on an order they do not own, the rejection is `ERR_INSUFFICIENT_PERMISSIONS` (priority 2) rather than `ERR_ORDER_NOT_FOUND` (priority 3) — the role check fires before any path-resource lookup, and the ownership component of the role check treats a non-owned resource as "role not permitted for this operation."

### 2.6. Geographic and Temporal Conventions

All geographic coordinates in this system are represented as signed decimal degrees: latitude in the range `[-90, 90]`, longitude in the range `[-180, 180]`. The fields `Nurse.home_lat`, `Nurse.home_lng`, `Order.service_lat`, `Order.service_lng`, `ServiceRecord.checkin_lat`, and `ServiceRecord.checkin_lng` all follow this convention. Distance computations between two coordinate pairs use the great-circle (Haversine) formula and yield kilometres rounded to three decimal places before being stored on `Dispatch.distance_km`.

All timestamps in the system are ISO 8601 UTC with three fractional digits — patient and operator inputs such as `scheduled_start`, `handover_at`, `checkin_at`, `completed_at`, `effective_at`, `expires_at`, and `cutoff_at`, and system-emitted timestamps alike. Time-of-day buckets used in fee computation read the UTC hour of the relevant timestamp; the day-of-week test ("weekend") likewise reads UTC.

Because the platform must respond to several time-driven transitions (dispatch acceptance windows expiring, certifications becoming `EXPIRING` or lapsing back to `PENDING`), an admin-only test-driving capability advances the logical clock to a supplied `to` instant; that capability replays every time-keyed side effect against the new now (see §3.6).

### 2.7. Monetary Precision and the Per-Component Rounding Rule

All monetary fields are stored as integer cents (`base_price_cents`, `estimated_fee_cents`, `final_fee_cents`, `gross_fee_cents`, `distance_surcharge_cents`, `time_of_day_surcharge_cents`, `package_deduction_cents`, `refund_cents`, `tax_cents`, `nurse_revenue_share_cents`, `platform_share_cents`, `compensation_cents`, `total_nurse_share_cents`, `total_platform_share_cents`). Whenever a calculation produces a fractional cent — typically after multiplying a base by a basis-points multiplier — the server applies round-half-up to the nearest integer cent. The rounding occurs **per component** before the components are summed: the time-of-day surcharge is rounded, the tax is rounded, the nurse share is rounded, and only then are these integer cents added together. Sum-then-round is incorrect and will diverge from the test contract on edge cases where two components each round in the same direction.

Rates expressed in basis points (`Nurse.revenue_share_bps`, the day/night/weekend multipliers, the tax rate) interpret 10000 as 100%. The `Nurse.rating` is the only non-cents monetary-adjacent field; it is a number with two decimal places, computed and stored with round-half-up.

### 2.8. Selector Determinism and Empty-Pool Fallback

Whenever a nurse must be selected for an order, the platform applies a deterministic candidate filter and a deterministic ranking. The filter and ranking are described inside §3.3 (where dispatch lives in the workflow narrative); the cross-cutting principle at this level is simply that the selector is **deterministic** — given the same candidate set and the same order, the same nurse is picked every time, and the tiebreak chain (lower composite score wins; on a four-decimal tie the smaller `distance_km` wins; on a still-perfect tie the lexicographically smaller `Nurse.id` wins) leaves no ambiguity. When the candidate pool is empty after filters and exclusions, the order transitions to `CANCELLED` with the `cancelled_reason` set to `ERR_NO_AVAILABLE_NURSE`, which is also the error code that surfaces when this fallback fires from the patient's perspective.

### 2.9. Cascading Side Effects and Audit Logging

State transitions in this system frequently mutate more than one row. A nurse becoming `DISQUALIFIED` cancels every `OFFERED` dispatch that nurse holds and triggers re-dispatch on each affected order; a logical clock advance crossing `Dispatch.accept_deadline` flips the dispatch to `EXPIRED` and triggers re-dispatch; a clock advance crossing `Nurse.certified_until` flips the nurse to `PENDING` and cancels every `OFFERED` dispatch that nurse holds; a logical clock advance crossing the warning window before `certified_until` flips the nurse to `EXPIRING`; a complaint resolution with a non-zero compensation amount mutates the corresponding settlement. Every such mutation refreshes the `updated_at` timestamp and bumps the `version` counter on each version-bearing entity it touches, including bystander entities whose own state flag did not change but whose business invariants are coupled to the primary mutation.

Auditable operations append a row to `AuditLog`. Every audit entry records the primary subject via `subject_type` (one of `ORDER`, `SERVICE_RECORD`, `COMPLAINT`, `NURSE`) and `subject_id`, the calling identity via `actor_role` and `actor_id`, the short verb in `action` (such as `CHECKIN`, `COMPLETE`, `CERTIFY`, `RECERTIFY`, `CERT_LAPSED`, `EXPIRY_WARNING`, `DISQUALIFY`, `WASTE_ARCHIVED`, `COMPLAINT_RESOLVE`, `COMPLAINT_REJECT`, or `COMPLAINT_SUBMIT`), and a `payload` snapshot of the request body or state diff. Audit rows are append-only — `created_at` is set on insert and the row is never updated.

### 2.10. Concurrency and Idempotency

Several operations admit concurrent attempts that must be serialized to a single winner. Two nurses simultaneously accepting offered dispatches for the same order — whether the same dispatch row or two parallel sibling rows — serialize to exactly one acceptance per order; the loser receives `ERR_DISPATCH_ALREADY_TAKEN` at HTTP 409, and any other still-`OFFERED` sibling dispatches for the same order are flipped to `CANCELLED` as a side effect of the winning acceptance. A patient cancellation racing against a dispatch acceptance serializes on the order's status; the loser receives `ERR_INVALID_STATE` at HTTP 409. Two compliance officers attempting to resolve the same complaint concurrently likewise serialize on the complaint's `stage` field; the loser receives `ERR_INVALID_STATE` because the stage has already left `MEDIATION` or `TRIAGE` by the time the second writer commits. Two attempts to start a payout-batch build while a `BUILDING` batch is already open serialize on the batch's status; the loser receives `ERR_PAYOUT_BATCH_ALREADY_BUILDING` at HTTP 409. Order creation accepts an `Idempotency-Key` request header scoped per patient; submitting the same key with a different payload, or replaying the same key within the same patient's scope, returns `ERR_IDEMPOTENCY_KEY_REUSED` at HTTP 409, while a faithful replay of the same key with the same payload deterministically returns the originally created order.

## 3. Business Logic & Workflows

### 3.1. Nurse Certification and the Path to Active Duty

A new nurse profile begins life with `certification_status` of `PENDING`, no `certified_until` date, and the boolean flags `license_verified` and `hospital_affiliation_verified` both false. The profile is created by a `PlatformAdmin` who supplies the legal `full_name`, the nurse's `gender` (one of `M`, `F`, or `O`), the spoken `languages` (an array of ISO 639-1 codes), the `license_number` (which must be unique across nurses), the `specialty_tags` array drawn from the closed set `{WOUND_CARE, IV_INFUSION, CATHETER_CARE, MATERNAL_NEWBORN, ELDERLY_CARE, PALLIATIVE}`, the home base coordinates `home_lat` and `home_lng`, and optionally a per-day workload ceiling `max_daily_orders` (default 6, must be at least 1) and a `revenue_share_bps` for the nurse's cut of net service revenue (default 7000, meaning 70%). The newly created profile is assigned an initial `rating` of 5.00.

Identity verification is event-driven. Two external handshakes — a nursing-license verifier and a hospital-affiliation verifier — return through the test event hook (`system=identity-verification`); their successful completion sets `license_verified` or `hospital_affiliation_verified` to true. A `ComplianceOfficer` then writes a `CertificationRecord` against the nurse with `kind` set to `INITIAL` and `outcome` set to `PASS`, supplying the `effective_at` timestamp at which the certification takes hold, optional `training_hours` representing continuing-education credit (must be at least 0; defaults to 0), and free-text `notes`. For this initial certification to advance the nurse from `PENDING` to `CERTIFIED`, three conditions must hold: `license_verified` must be true, `hospital_affiliation_verified` must be true, and the cumulative sum of `training_hours` over the nurse's `INITIAL` and `TRAINING` records must reach the minimum training threshold of 24 hours. When all three hold, the nurse advances to `CERTIFIED`, `certified_until` is set to the supplied `effective_at` plus a recertification validity period of 365 days, and an audit row is appended with action `CERTIFY`.

Recertification works the same way after the certification has begun to expire. Thirty days before `certified_until`, a logical clock advance crossing the warning threshold flips the nurse to `EXPIRING` and emits an `EXPIRY_WARNING` audit entry. A subsequent `CertificationRecord` of `kind` `RECERTIFICATION` with `outcome` `PASS` returns the nurse to `CERTIFIED` and resets `certified_until` to its `effective_at` plus 365 days, provided the training accumulated since the last successful certification reaches at least 12 hours — half the initial-certification floor, on the understanding that the active practitioner already holds the foundational training. If the clock advances past `certified_until` itself before recertification lands, the nurse drops to `PENDING`, every `OFFERED` dispatch for that nurse flips to `CANCELLED`, and a `CERT_LAPSED` audit row is appended; the nurse must restart the certification path before they can be dispatched again. Disqualification is the terminal outcome: a `CertificationRecord` with `kind` `DISQUALIFICATION` (regardless of `outcome`) sends a non-disqualified nurse straight to `DISQUALIFIED`, cancels every `OFFERED` dispatch that nurse holds, triggers re-dispatch on each affected order, and emits a `DISQUALIFY` audit row. A nurse who is already `DISQUALIFIED` cannot be transitioned again — the request is rejected with `ERR_INVALID_STATE`.

### 3.2. Service Catalog, Patient Booking, and Eligibility Review

The service catalog is owned by `PlatformAdmin`. Each `ServiceItem` carries a unique catalog `code` (such as `IV001`), a display `name`, a patient-facing `description` and clinical `contraindications`, the single `required_skill` from the same six-tag set the nurses use, the integer `base_price_cents` (must be at least 0), the standard `duration_minutes` (must be greater than 0), and three flags: `requires_medical_doc` indicating whether an order against this item must attach a prescription or discharge-summary URL, `requires_eligibility_review` indicating whether orders against this item must be approved by a `ComplianceOfficer` before dispatch can begin, and `active` (default true) which soft-disables the item without removing it. Listing endpoints accept `active?` and other filters; an inactive item still exists for historical reads but cannot be the target of new orders.

Patient ordering submits a request body specifying the `service_item_code` of the chosen item, the `service_address` text and its decoded coordinates `service_lat` and `service_lng`, the requested `scheduled_start`, optionally a `preferred_gender` (one of `M`, `F`, or `ANY`; defaulting to `ANY`), an optional `preferred_language` (an ISO 639-1 code or the literal `any`; default `any`), an optional `medical_doc_url`, and an optional `package_id` to draw a credit from a prepaid package. Order creation enforces several gates before a row is inserted. The chosen catalog item must exist and have `active` true (otherwise `ERR_RESOURCE_LINK_INVALID`). When the catalog item's `requires_medical_doc` flag is true, the supplied `medical_doc_url` must be non-empty (otherwise `ERR_MEDICAL_DOC_REQUIRED`). When a `package_id` is supplied, the referenced package must exist (`ERR_PACKAGE_NOT_FOUND` otherwise), its `patient_id` must equal the calling patient's `X-User-ID` (otherwise `ERR_RESOURCE_LINK_INVALID`), its `service_item_code` must match the order's `service_item_code` (also `ERR_RESOURCE_LINK_INVALID` on mismatch), its `status` must be `ACTIVE`, and its `used_credits` must be strictly less than its `total_credits` (otherwise `ERR_INSUFFICIENT_PACKAGE_CREDIT`). The new order is initialized with `status` `SUBMITTED`, `payment_status` `UNPAID`, and `dispatch_attempt_count` of 0.

Immediately after insertion, the server computes the forward-looking fee estimate and stores it on `estimated_fee_cents`. The estimate is built component by component: the base is the catalog item's `base_price_cents`; the distance surcharge is computed by subtracting the free-distance allowance of 5 kilometres from the kilometre estimate from a default origin to the service address, taking the result no lower than zero, rounding up to the next whole kilometre, and multiplying by the distance rate of 200 cents per kilometre; the time-of-day surcharge takes the UTC hour of `scheduled_start` and selects a multiplier — 13000 basis points when the hour is before 6 or at-or-after 22 (the night band), 11500 basis points when `scheduled_start` falls on Saturday or Sunday outside the night band (the weekend band), and 10000 basis points (no premium) otherwise — and the surcharge is the base price multiplied by the difference between the chosen multiplier and 10000, divided by 10000, rounded half-up to the nearest integer cent. When the order is using a valid active package with credits remaining, a projected package deduction equal to the base price is subtracted; otherwise the projected deduction is zero. The pre-tax net is the maximum of zero and the sum of base, distance surcharge, and time-of-day surcharge minus the projected package deduction. Tax is the net multiplied by 600 basis points divided by 10000, rounded half-up. The estimate stored on `estimated_fee_cents` is the net plus tax. Each component is rounded before the sum is taken — sum-then-round is wrong.

When the catalog item's `requires_eligibility_review` is false, the order auto-routes from `SUBMITTED` to `AWAITING_DISPATCH` and the matching engine creates a single `Dispatch` row in the same request. When `requires_eligibility_review` is true, the order auto-routes from `SUBMITTED` to `UNDER_REVIEW` instead, and the engine waits. A `ComplianceOfficer` then resolves the review by submitting a `decision` of `APPROVE` or `REJECT` with optional `notes`. Approval moves the order from `UNDER_REVIEW` to `AWAITING_DISPATCH` and triggers nurse selection; rejection moves the order from `UNDER_REVIEW` to `REJECTED`, and if the payment authorization had succeeded by then the platform emits a refund event and sets `payment_status` to `REFUNDED`. Because no package credit is consumed before dispatch, rejection at this stage does not mutate any `Package`. Independently of the review outcome, the payment system emits an authorization event (`system=payment, event_type=AUTHORIZED`) on order creation when `estimated_fee_cents` is greater than zero, advancing `payment_status` from `UNPAID` to `AUTHORIZED`.

A patient may cancel before the nurse has accepted a dispatch — that is, while the order is in `SUBMITTED`, `UNDER_REVIEW`, or `AWAITING_DISPATCH`. Cancellation accepts an optional free-text `cancelled_reason`, transitions the order to `CANCELLED`, flips any still-`OFFERED` dispatches for the order to `CANCELLED`, and refunds the authorized payment by setting `payment_status` to `REFUNDED`. Cancellation attempts after the order has reached `DISPATCHED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`, or `REJECTED` are rejected with `ERR_INVALID_STATE`.

### 3.3. Matching, Dispatch, and the Acceptance Window

Whenever an order is in `AWAITING_DISPATCH` — at first entry from `SUBMITTED` or `UNDER_REVIEW`, and on each re-entry from `DISPATCHED` triggered by a rejection or expiry — the selector builds a candidate set and ranks it. A nurse is a candidate for the order only if every one of the following holds: the nurse's `certification_status` is `CERTIFIED` or `EXPIRING` and is therefore not `PENDING` and not `DISQUALIFIED`; the catalog item's `required_skill` appears in the nurse's `specialty_tags`; the nurse is not associated with any prior `REJECTED` or `EXPIRED` dispatch on this same order; the great-circle distance from the nurse's `home_lat`/`home_lng` to the order's `service_lat`/`service_lng` is no greater than the maximum dispatch radius of 15 kilometres; the count of the nurse's currently `DISPATCHED` or `IN_PROGRESS` orders on the local calendar day of the request is strictly less than that nurse's `max_daily_orders`; the order's `preferred_gender` is `ANY` or the nurse's `gender` matches the requested preferred gender; and the order's `preferred_language` is the literal `any` or appears in the nurse's `languages`.

The ranking is a weighted-score where lower scores win. The score is the sum of three normalized terms: the `W_DIST` weight of 0.5 multiplied by the candidate's distance divided by the 15-kilometre radius; the `W_LOAD` weight of 0.3 multiplied by the candidate's current load divided by their `max_daily_orders`; and the `W_RATING` weight of 0.2 multiplied by the gap between 5.0 and the candidate's `rating`. The composite score is computed to four decimal places with round-half-up, and the lowest score wins. When two candidates tie at four decimals, the one with the smaller `distance_km` wins; if still tied, the lexicographically smaller `Nurse.id` wins. The selected nurse's id becomes the dispatch's `nurse_id`, the parent order's id becomes the dispatch's `order_id`, the chosen distance becomes `distance_km`, and the composite score is preserved on `ranked_score`. The dispatch row is created with `status` `OFFERED`, `offered_at` set to the current instant, and `accept_deadline` set to `offered_at` plus the acceptance-window length (a system constant; see §3.6). The order's `dispatch_attempt_count` is incremented by exactly one. When the candidate set is empty after filters and exclusions, the order is sent straight to `CANCELLED` with `cancelled_reason` set to `ERR_NO_AVAILABLE_NURSE` and the same error code surfaces to the API caller.

A nurse who holds an `OFFERED` dispatch may accept it or reject it. Acceptance and rejection both require the calling `X-User-ID` to equal `Dispatch.nurse_id` (otherwise `ERR_RESOURCE_LINK_INVALID`), and both require the current instant to be strictly before `accept_deadline` — at-or-after the deadline yields `ERR_DISPATCH_WINDOW_EXPIRED` regardless of whether the call would have been an accept or a reject. Acceptance additionally requires that the order be in `AWAITING_DISPATCH` and that no other dispatch on the same order has already reached `ACCEPTED`; the second writer in a race loses with `ERR_DISPATCH_ALREADY_TAKEN`. On a successful acceptance, the dispatch flips from `OFFERED` to `ACCEPTED`, the order advances from `AWAITING_DISPATCH` to `DISPATCHED`, and every other still-`OFFERED` sibling dispatch on the same order is flipped to `CANCELLED` so that the winner stands alone. Rejection accepts an optional free-text `rejection_reason`, flips the dispatch to `REJECTED`, and triggers a re-dispatch attempt on the order: provided `dispatch_attempt_count` is strictly less than the cap of 5 and no other `ACCEPTED` dispatch exists, the order returns to `AWAITING_DISPATCH`, the selector runs again excluding any nurse tied to a prior `REJECTED` or `EXPIRED` dispatch on this order, and a new `Dispatch` row is created. If the selector returns empty on this re-run, the order moves to `CANCELLED` with the same `ERR_NO_AVAILABLE_NURSE` reason. The same re-dispatch chain is triggered when the logical clock crosses an `OFFERED` dispatch's `accept_deadline` (the dispatch flips to `EXPIRED`) or when a nurse becomes `DISQUALIFIED` while holding the offer (the dispatch flips to `CANCELLED`).

### 3.4. On-Site Service Execution and Medical Waste

Once the order is `DISPATCHED`, the assigned nurse arrives on site and performs the initial check-in by submitting a `checkin_at` timestamp, the GPS coordinates `checkin_lat` and `checkin_lng`, the boolean `face_verification_passed`, and optionally the initial entries for `checklist_items`, `vitals`, `medications_administered`, `evidence_urls`, and `abnormal_events`. Two safety gates fire at this moment in the order they are listed: the geofence — the great-circle distance between the check-in coordinates and the order's `service_address` coordinates must be no greater than the check-in geofence radius of 0.5 kilometres, otherwise `ERR_CHECKIN_OUT_OF_RANGE` — and then identity verification — `face_verification_passed` must be true, otherwise `ERR_FACE_VERIFICATION_FAILED`. A successful check-in creates the `ServiceRecord` with `status` `STARTED`, advances the order from `DISPATCHED` to `IN_PROGRESS`, and appends an audit row with action `CHECKIN`. Only the nurse named on the dispatch may post the check-in; the operation is also rejected if a `ServiceRecord` already exists for the order.

During execution, the nurse appends data to the same `ServiceRecord` — checklist progress as an array of `{step, done, note}`, vital-signs measurements as an array of `{ts, type, value, unit}` where `type` is one of `BP`, `HR`, `TEMP`, `SPO2`, or `GLU`, medications administered as an array of `{name, dose, route, ts}`, photo-or-signature `evidence_urls`, and abnormal events as an array of `{ts, severity, description}` where `severity` is one of `LOW`, `MEDIUM`, or `HIGH`. The first append after check-in advances the record from `STARTED` to `IN_PROGRESS`. When the nurse declares the procedure complete, three completion gates fire: every entry in `checklist_items` must have `done` set to true, the `evidence_urls` array must contain at least one entry, and every abnormal event with `severity` `HIGH` must carry a non-empty `description` note. Failure of any gate yields `ERR_CHECKLIST_INCOMPLETE`. On success, the server stamps `completed_at` with the current instant and the record advances from `IN_PROGRESS` to `AWAITING_PATIENT_CONFIRM`.

For service items whose `required_skill` is `WOUND_CARE`, `IV_INFUSION`, or `CATHETER_CARE`, every clinical procedure produces medical waste, and each waste item must be registered before the order can be confirmed. The nurse posts a `WasteEntry` for each registered item, supplying the `category` (one of `SHARPS`, `INFECTIOUS`, or `PHARMACEUTICAL`), the positive `quantity`, and the `unit` (one of `PCS`, `LITERS`, or `KG`). The waste row begins in `REGISTERED` and tracks `created_at`. When the disposal unit takes custody, the nurse patches the row with `sealed` set to true, the qualified `disposal_unit_id`, and the `handover_at` timestamp; this transition (which requires `sealed` true and a non-empty `disposal_unit_id`) advances the row to `HANDED_OVER`. The medical-waste-disposal system later returns through the test event hook (`system=medical-waste-disposal, event_type=CERTIFICATE_ISSUED`) carrying the `certificate_url`; the row then advances to `ARCHIVED`, the URL is stored, and an audit row with action `WASTE_ARCHIVED` is appended. While the row is `HANDED_OVER` and pending archival, `certificate_url` remains null.

The patient closes the order by confirming completion. Three preconditions hold at this moment: the order must be `IN_PROGRESS`, the `ServiceRecord.status` must be `AWAITING_PATIENT_CONFIRM`, and — when the catalog item's `required_skill` is in the waste-producing trio — every `WasteEntry` belonging to the order must already be `ARCHIVED`; an unarchived entry blocks confirmation with `ERR_WASTE_NOT_ARCHIVED`. On success the order advances from `IN_PROGRESS` to `COMPLETED`, the service record advances from `AWAITING_PATIENT_CONFIRM` to `COMPLETED`, the final settlement is computed and a `Settlement` row is created with `status` `FINALIZED`, the payment is captured (`payment_status` advances from `AUTHORIZED` to `CAPTURED`), an `ORDER_COMPLETED` IM event is emitted (audit-only), and if a package was used its `used_credits` is incremented by exactly one — when `used_credits` reaches `total_credits`, the package's `status` flips to `EXHAUSTED`. An audit row with action `COMPLETE` is appended.

### 3.5. Settlement, Refunds, Complaints, and Payouts

Settlement at completion uses the chronological-replay algorithm and reads actual values rather than estimates. The base remains the catalog item's `base_price_cents`. The distance surcharge takes the **actual** `distance_km` from the accepted dispatch — not the planning-time estimate — subtracting the 5-kilometre free allowance, taking the result no lower than zero, rounding up to the next whole kilometre, and multiplying by 200 cents per kilometre, and the result lands on `Settlement.distance_surcharge_cents`. The time-of-day surcharge takes the UTC hour of `ServiceRecord.checkin_at` — not the planned `scheduled_start` — and selects 13000 basis points for the night band (hour before 6 or at-or-after 22), 11500 basis points for a weekend day-band check-in (Saturday or Sunday outside the night band), and 10000 basis points otherwise; the surcharge is the base multiplied by the difference between the chosen multiplier and 10000, divided by 10000, rounded half-up to the nearest integer cent, stored on `Settlement.time_of_day_surcharge_cents`. The package deduction is the base price when a package was actually used at completion, zero otherwise, stored on `Settlement.package_deduction_cents`. The pre-tax `gross_fee_cents` is the maximum of zero and the sum of base, distance surcharge, and time-of-day surcharge minus the package deduction. The `tax_cents` is the gross multiplied by 600 basis points divided by 10000, rounded half-up. The `nurse_revenue_share_cents` is the gross multiplied by the assigned nurse's `revenue_share_bps` divided by 10000, rounded half-up; the `platform_share_cents` is the gross minus the nurse share. Tax is retained entirely by the platform reserve and is not split into the nurse's share. The total charge stored on `Order.final_fee_cents` is the gross plus tax. Each component is rounded before the components are summed. Estimated and final fees may differ — an actual dispatch farther from the default origin pushes the surcharge up; an actual check-in across a time band can shift the multiplier; a package planned for use but ultimately not consumed (or vice versa) flips the deduction.

Refunds are initiated by a `ComplianceOfficer` against a completed order. The refund window is 24 hours after `ServiceRecord.completed_at`; a refund requested strictly later than 24 hours after completion is rejected with `ERR_REFUND_WINDOW_EXPIRED`. Within the window, the refund amount is computed in tiers keyed on elapsed hours. When the elapsed time is at-or-below 1 hour, the refund equals `gross_fee_cents` plus `tax_cents` — a full refund. When the elapsed time is above 1 hour but at-or-below 6 hours, the refund is half of the gross-plus-tax sum, rounded half-up. When the elapsed time is above 6 hours but at-or-below 24 hours, the refund is twenty percent of the gross-plus-tax sum, rounded half-up. The lower-bound inclusivity of each tier means that exactly 1.0 hour is a full refund and 1.0001 hours is a fifty-percent refund. The refund target settlement must have `status` of `FINALIZED` or `PAID_OUT`. On a successful refund, `Settlement.refund_cents` is set to the computed value, `Settlement.status` advances to `REVERSED`, and `payment_status` advances from `CAPTURED` to `REFUNDED`. When the original settlement had already been included in a payout batch (`status` was `PAID_OUT`), the nurse's share is debited from the next payout batch.

Complaints submitted by patients about completed orders begin in `SUBMITTED` and carry the patient's `description` text and a `category` drawn from `NURSE_MISCONDUCT`, `SERVICE_QUALITY`, `BILLING`, `SAFETY`, or `OTHER`. The system copies the order's assigned nurse onto `Complaint.nurse_id` and the patient identifier onto `Complaint.patient_id` at submission, and emits an audit row with action `COMPLAINT_SUBMIT`. A `ComplianceOfficer` triages the complaint — the `SUBMITTED` to `TRIAGE` transition derives `routing` from `category`: it is `NURSE_RELATED` when `category` is `NURSE_MISCONDUCT` or `SAFETY`, and `SERVICE_RELATED` for the other three categories. From `TRIAGE` the officer either escalates to `MEDIATION` or resolves with `decision` of `REJECT`; the rejection path emits `COMPLAINT_REJECT`. From `MEDIATION` the officer either resolves the complaint with `decision` of `UPHOLD` — carrying the optional `compensation_cents`, the optional `rating_impact`, and the optional `resolution_notes` — which advances the complaint's `stage` to `RESOLVED`, or instead rejects.

Resolution applies several gates and effects together. The `compensation_cents` must not exceed the subject settlement's `gross_fee_cents`, otherwise `ERR_COMPENSATION_EXCEEDS_FEE`. The `rating_impact` must be in the range `[-1.0, 0]` when `routing` is `NURSE_RELATED`, and must be exactly 0 when `routing` is `SERVICE_RELATED`. On a successful upheld resolution that advances the complaint to `RESOLVED`, the `rating_impact` is applied to the nurse's `rating` and the result is clamped to the closed interval from 1.00 to 5.00; when `compensation_cents` is greater than zero, the amount is added to `Settlement.refund_cents`, and if the settlement was previously `FINALIZED` or `PAID_OUT` its `status` is moved to `REVERSED`; an audit row with action `COMPLAINT_RESOLVE` is appended. A rejected resolution likewise audits with `COMPLAINT_REJECT`. The aggregate `Nurse.rating` itself is computed over the latest 50 ratings — one implicit 5.0 per `COMPLETED` order without an upheld nurse-related complaint, and one (5.0 plus the `rating_impact`) per `COMPLETED` order whose nurse-related complaint resolved with a non-zero impact. The 50-row window is keyed on `ServiceRecord.completed_at` descending with the order's `id` lexicographic descending as tiebreak; the mean is rounded half-up to two decimals and clamped to the closed interval from 1.00 to 5.00. A nurse with fewer than one rating retains the initialization value of 5.00.

Periodic payouts are built by `PlatformAdmin`. The build request supplies a `cutoff_at` instant; the server gathers every `Settlement` whose `status` is `FINALIZED`, whose `payout_batch_id` is null, and whose `created_at` is at-or-before the cutoff (the upper bound is inclusive). The batch row is created in `BUILDING`, the gathered settlements are atomically marked with the new `payout_batch_id` and their `status` advanced to `PAID_OUT`, the batch's `total_settlements`, `total_nurse_share_cents` (the sum of `nurse_revenue_share_cents` across the included rows), and `total_platform_share_cents` (the sum of `platform_share_cents`) are populated, and the batch's `status` advances to `PAID`. Settlements with `status` of `REVERSED`, `PENDING`, or already paid out are excluded by construction. Only one `BUILDING` batch may exist at a time; an attempt to start a second concurrent build is rejected with `ERR_PAYOUT_BATCH_ALREADY_BUILDING`.

### 3.6. Time-Driven Effects and External Event Ingress

Several transitions are driven by the passage of time rather than by an explicit operator action. To make them testable, the platform exposes an admin-only test-driving capability that advances the logical clock to a supplied `to` instant. Every advance replays the complete chain of time-keyed side effects. Every still-`OFFERED` `Dispatch` whose `accept_deadline` is at-or-before the new now flips to `EXPIRED` and triggers re-dispatch on the parent order (subject to the same `MAX_DISPATCH_ATTEMPTS` cap of 5). Every nurse whose `certified_until` is at-or-before the new now flips to `PENDING`, every still-`OFFERED` dispatch they hold is flipped to `CANCELLED`, and a `CERT_LAPSED` audit row is appended. Every nurse whose `certified_until` minus 30 days is at-or-before the new now while `certified_until` itself is strictly after the new now flips from `CERTIFIED` to `EXPIRING`, with an `EXPIRY_WARNING` audit row.

The dispatch acceptance window — the `Dispatch.accept_deadline` minus `Dispatch.offered_at` — is a fixed system constant. So is the certification validity period of 365 days, the expiry-warning lead-time of 30 days, the initial-certification training floor of 24 hours and the recertification floor of 12 hours, the dispatch radius of 15 kilometres, the check-in geofence radius of 0.5 kilometres (500 metres), the maximum dispatch attempts of 5, and the refund window of 24 hours.

The platform also accepts external-system events through a separate test hook. Events from `system=identity-verification` set `Nurse.license_verified` or `Nurse.hospital_affiliation_verified` to true depending on the event type. Events from `system=medical-waste-disposal` with `event_type` of `CERTIFICATE_ISSUED` advance a matching `WasteEntry` from `HANDED_OVER` to `ARCHIVED` and store the supplied `certificate_url`. Events from `system=payment` with `event_type` of `AUTHORIZED`, `CAPTURED`, or `REFUNDED` mirror the corresponding `Order.payment_status` change. Events from `system=im` with `event_type` of `ORDER_COMPLETED` are recorded for audit only and produce no state mutation.

### 3.7. Cross-Cutting Read Surfaces and Audit Visibility

Several read endpoints are scoped by role identity. Patients see only their own orders, dispatches on their orders, settlements, packages, and complaints. Nurses see only their own profile, their own certification records, the orders dispatched or assigned to them, dispatches whose `nurse_id` equals their `X-User-ID`, and waste entries on those assigned orders. `ComplianceOfficer` and `PlatformAdmin` have broader read scopes per the §1.7 RBAC matrix. Audit logs are visible only to `PlatformAdmin` and `ComplianceOfficer`, and they are filterable by `subject_type` and `subject_id`.

The list endpoint for nurses accepts query filters `certification_status` and `specialty` to narrow results; the orders list accepts `status`; the complaints list accepts `stage`; the service-items list accepts `active`. All list endpoints obey the §2.3 pagination contract — `limit` and `offset` defaults of 10 and 0, max 100, sort by `created_at` ascending.

## 4. Endpoint Definitions

The endpoints below form the complete external API surface. Operations that create a new resource return HTTP 201; operations that modify an existing resource (including state-machine transitions on resources that already exist) return HTTP 200. The `/_clock/advance` and `/_events/emit` test hooks are fixed at HTTP 200 because they do not create user-visible resources. Authentication and authorization apply per §2.1 and §2.5; refer to §3 for request bodies, response payloads, and side-effect chains — they are intentionally not duplicated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/nurses` | Register a nurse profile (initial state `PENDING`). | `PlatformAdmin` |
| GET | `/nurses` | List nurses with optional `certification_status` and `specialty` filters. | `PlatformAdmin`, `ComplianceOfficer` |
| GET | `/nurses/{nurseId}` | Get a nurse by id (a `Nurse` may fetch only their own profile). | `PlatformAdmin`, `ComplianceOfficer`, `Nurse` |
| POST | `/nurses/{nurseId}/certification-records` | Append a certification, training, recertification, or disqualification record. | `ComplianceOfficer` |
| GET | `/nurses/{nurseId}/certification-records` | List certification records for a nurse. | `PlatformAdmin`, `ComplianceOfficer`, `Nurse` |
| POST | `/service-items` | Create a catalog item. | `PlatformAdmin` |
| GET | `/service-items` | List catalog items with optional `active` filter. | `PlatformAdmin`, `ComplianceOfficer`, `Patient` |
| GET | `/service-items/{code}` | Get one catalog item by `code`. | `PlatformAdmin`, `ComplianceOfficer`, `Patient` |
| POST | `/orders` | Create an order; auto-routes to `UNDER_REVIEW` or `AWAITING_DISPATCH`; honors `Idempotency-Key`. | `Patient` |
| GET | `/orders` | List orders with optional `status` filter (scoped by role). | `Patient`, `PlatformAdmin`, `ComplianceOfficer`, `Nurse` |
| GET | `/orders/{orderId}` | Get an order by id (scoped by role). | `Patient`, `PlatformAdmin`, `ComplianceOfficer`, `Nurse` |
| POST | `/orders/{orderId}/eligibility-review` | Approve or reject an order requiring compliance review. | `ComplianceOfficer` |
| POST | `/orders/{orderId}/cancel` | Patient cancels prior to dispatch acceptance. | `Patient` |
| POST | `/orders/{orderId}/confirm-completion` | Patient confirms service done; triggers settlement and capture. | `Patient` |
| POST | `/orders/{orderId}/refund` | Refund a completed order per the tiered refund rules. | `ComplianceOfficer` |
| GET | `/orders/{orderId}/dispatches` | List dispatch attempts on an order. | `Patient`, `PlatformAdmin`, `ComplianceOfficer` |
| GET | `/dispatches/{dispatchId}` | Get a dispatch row (a `Nurse` may fetch only own dispatches). | `PlatformAdmin`, `ComplianceOfficer`, `Nurse` |
| POST | `/dispatches/{dispatchId}/accept` | Nurse accepts an offered dispatch. | `Nurse` |
| POST | `/dispatches/{dispatchId}/reject` | Nurse rejects an offered dispatch. | `Nurse` |
| POST | `/orders/{orderId}/service-record` | Nurse on-site check-in; creates the `ServiceRecord`. | `Nurse` |
| PATCH | `/orders/{orderId}/service-record` | Append checklist, vitals, medications, evidence, abnormal events. | `Nurse` |
| POST | `/orders/{orderId}/service-record/finish` | Nurse declares service done; awaits patient confirmation. | `Nurse` |
| POST | `/orders/{orderId}/waste-entries` | Register a medical-waste item. | `Nurse` |
| PATCH | `/orders/{orderId}/waste-entries/{wasteId}` | Update sealing and handover info on a waste entry. | `Nurse` |
| GET | `/orders/{orderId}/waste-entries` | List waste entries for an order. | `Nurse`, `PlatformAdmin`, `ComplianceOfficer` |
| POST | `/packages` | Create a prepaid package for a patient. | `PlatformAdmin` |
| GET | `/packages` | List packages (a `Patient` sees only their own). | `Patient`, `PlatformAdmin` |
| GET | `/orders/{orderId}/settlement` | Get the settlement for an order. | `Patient`, `PlatformAdmin`, `ComplianceOfficer` |
| POST | `/payout-batches` | Build a periodic payout batch. | `PlatformAdmin` |
| GET | `/payout-batches` | List payout batches. | `PlatformAdmin` |
| POST | `/complaints` | Patient submits a complaint about a completed order. | `Patient` |
| GET | `/complaints` | List complaints with optional `stage` filter (scoped by role). | `Patient`, `PlatformAdmin`, `ComplianceOfficer` |
| POST | `/complaints/{complaintId}/triage` | Triage a submitted complaint and assign `routing`. | `ComplianceOfficer` |
| POST | `/complaints/{complaintId}/escalate-mediation` | Escalate from `TRIAGE` to `MEDIATION`. | `ComplianceOfficer` |
| POST | `/complaints/{complaintId}/resolve` | Resolve or reject a complaint at `TRIAGE` or `MEDIATION`. | `ComplianceOfficer` |
| GET | `/audit-logs` | List audit log entries with optional `subject_type`/`subject_id` filters. | `PlatformAdmin`, `ComplianceOfficer` |
| POST | `/_clock/advance` | Test hook: advance the logical clock to a supplied `to` instant. | `PlatformAdmin` |
| POST | `/_events/emit` | Test hook: emit an external-system event with `system`, `event_type`, and `payload`. | `PlatformAdmin` |

## 5. Error Code Catalogue

Trigger conditions for each error live in §2 and §3 narratives. The table below enumerates the canonical identifier and HTTP status of every error the API can return.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NURSE_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_SERVICE_ITEM_NOT_FOUND` | 404 |
| `ERR_DISPATCH_NOT_FOUND` | 404 |
| `ERR_WASTE_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DISPATCH_ALREADY_TAKEN` | 409 |
| `ERR_DISPATCH_WINDOW_EXPIRED` | 409 |
| `ERR_WASTE_NOT_ARCHIVED` | 409 |
| `ERR_PAYOUT_BATCH_ALREADY_BUILDING` | 409 |
| `ERR_IDEMPOTENCY_KEY_REUSED` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_RESOURCE_LINK_INVALID` | 422 |
| `ERR_MEDICAL_DOC_REQUIRED` | 422 |
| `ERR_NURSE_NOT_CERTIFIED` | 422 |
| `ERR_CHECKIN_OUT_OF_RANGE` | 422 |
| `ERR_FACE_VERIFICATION_FAILED` | 422 |
| `ERR_CHECKLIST_INCOMPLETE` | 422 |
| `ERR_NO_AVAILABLE_NURSE` | 422 |
| `ERR_REFUND_WINDOW_EXPIRED` | 422 |
| `ERR_COMPENSATION_EXCEEDS_FEE` | 422 |
| `ERR_INSUFFICIENT_PACKAGE_CREDIT` | 422 |
