# Passport & Visa Expediting API — Product Requirements Document

## 1. Introduction

A passport and visa expediting service sits between a traveller and a government that will not talk to them directly. The traveller hands over the one physical object that proves who they are — the passport book — and expects it back, stamped, before a departure date that does not move. The expediter, meanwhile, is holding two kinds of money that must never be confused: a consular fee that belongs to the government the moment it is handed over, and a service fee that the expediter earns by doing the work. This document specifies the API for the operational spine of such a business: taking the order, pricing it across both money streams, assembling and reviewing the applicant's paperwork, booking consular interviews, physically moving the book through a chain of couriers, tracking the agency's turnaround clock through the pauses that evidence requests introduce, and delivering the finished document to the traveller's door.

The system is deliberately built around axes that move independently. An order's workflow position, its payment position, the identity of whoever physically holds the passport, and the verdict on whether the projected completion date still beats the travel date are four separate state machines on the same record, and a change to one of them routinely leaves the other three untouched. That independence is the whole point: a tier upgrade can re-open a settled balance without disturbing the workflow, a passport can sit in agency custody while the delivery address is corrected, and an evidence request can stop the service-level clock without stopping anything else. Underneath, four conservation rules hold at every instant — money is conserved across a four-way partition, exactly one party holds the passport, the agency clock is partitioned exactly into running and paused segments, and a split of one order into two neither creates nor destroys a cent.

Everything in this specification is driven by a **logical clock** rather than wall-clock time, so that deadlines, cutoffs, lead times and validity windows can be exercised deterministically. Every endpoint is mounted under the `/expediting` prefix. The remainder of this document defines the global contract (§2), the business logic and workflows (§3), the endpoint surface (§4), and the error catalogue (§5).

---

## 2. Global Specifications & System-Wide Principles

### 2.1. Operators, Roles and Identity

Every request must carry two headers: `X-User-ID` and `X-User-Role`. `X-User-Role` names the acting role and must be one of exactly six declared values, spelled precisely as follows: `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler`.

A request whose `X-User-Role` header is absent, or whose value is not one of those six strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). `X-User-ID` must additionally be present whenever the acting role is `CaseManager`, `Traveler`, `ComplianceOfficer`, `AgencyLiaison` or `CourierOps`; its absence for any of those five roles is likewise `ERR_UNAUTHENTICATED`. `PlatformAdmin` is the single role for which `X-User-ID` may be omitted. Once authenticated, a role that does not appear in the called endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Five of the six roles carry an **opaque** identity. When `X-User-Role` is `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison` or `ComplianceOfficer`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server records it in the places where a workflow demands attribution — `quoted_by_user_id` and `submitted_by_user_id` on an order, `acknowledged_by_user_id` when a compliance acknowledgment is granted, `reviewed_by_user_id` on a document decision, `signed_by_user_id` on a form signature — but it never compares that value to any row's `id`.

The sixth role is different. When `X-User-Role` is `Traveler`, `X-User-ID` is the `id` of the acting `Applicant` row. A `Traveler` may only act on, or read, an order that carries an applicant whose `id` equals `X-User-ID`. The membership test walks whatever the request names: the order directly, or the order reachable from the applicant, document slot, photo, prepared form, appointment, evidence request or shipment named in the path. A `Traveler` request that resolves to an order carrying no such applicant is rejected with `ERR_NOT_ORDER_MEMBER` (HTTP 403). This test runs on every endpoint whose authorized-role list includes `Traveler` — reads as well as writes.

The role model is a **segregation-of-duties** model in one specific place: a `CaseManager` who produced the standing quote on an order may not be the `CaseManager` who submits that same order to the agency. The operational consequences of that rule are described in §3.9.

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

### 2.3. Pagination, List Ordering and Filtering

Every list endpoint accepts `limit` and `offset` as query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0. A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_VALIDATION` (HTTP 400). List responses populate `limit`, `offset`, `total_count` and `has_more` in `meta`; `total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true exactly when the sum of `offset` and the number of rows returned is strictly less than `total_count`.

**Default ordering.** Unless a list endpoint is named in the exception list below, rows are returned sorted by `created_at` ascending, with `id` ascending as the tie-break when two rows carry the same `created_at`. Because the logical clock is deliberately coarse and many rows are written within a single clock instant, the tie-break is load-bearing and must be implemented.

**Ordering exceptions.** Three list endpoints sort on a domain key instead:

- An order's courier legs are returned sorted by `leg_index` ascending, tie-broken by `created_at` ascending and then `id` ascending.
- An order's custody events are returned sorted by `acquired_at` ascending, tie-broken by `created_at` ascending and then `id` ascending.
- An order's SLA segments are returned sorted by `started_at` ascending, tie-broken by `created_at` ascending and then `id` ascending.

**Filter semantics.** Every filter query parameter compares by exact, case-sensitive string equality against the value stored on the row — there is no prefix matching, no case folding and no partial matching. Filters that name an enum-typed column (`workflow_status`, `visa_type`, `status`, `prep_status`, `readiness_status`, `review_status`, `compliance_status`, `booking_status`, `leg_status`, `rfe_status`, `stream`, `kind`) are compared the same way. A filter value that is not a member of the column's enumeration is **not** an error: it simply matches no stored row, and the endpoint returns an empty array with `total_count` 0 and `has_more` false. Identifier filters (`catalog_item_id`, `consulate_id`, `parent_order_id`, `applicant_id`, `slot_id`, `form_code`, `nationality_code`, `destination_country`) behave identically — an unknown value yields an empty page rather than a 404. When several filters are supplied they are combined conjunctively: a row must match every supplied filter to be returned.

### 2.4. Resource Identity, Timestamp Rendering and the Version Counter

Every stored row carries an `id` that is a server-minted UUID string. Identifiers never carry a type prefix and are never supplied by the client. Every stored row also carries `created_at`, the logical-clock instant at which the row was written.

Most entities additionally carry `updated_at` and `version`. `version` is an integer that is **1 on creation** and increases by exactly 1 each time a request mutates the row; `updated_at` is set to the logical clock at the same moment and equals `created_at` until the first mutation. Seventeen entities exist in this system; thirteen of them carry the full set — `ServiceCatalogItem`, `AgencyForm`, `Consulate`, `AppointmentSlot`, `Order`, `Applicant`, `ApplicantDocument`, `PhotoAsset`, `PreparedForm`, `Appointment`, `CourierLeg`, `RFE` and `Shipment`.

Four entities are **append-only records** and deliberately carry neither `updated_at` nor `version`: `DocumentRequirement`, `CustodyEvent`, `LedgerEntry` and `SlaSegment`. Rows of these four types expose only `id` and `created_at` alongside their own attributes. `CustodyEvent`, `LedgerEntry` and `SlaSegment` are never edited in place after creation with one exception apiece that the workflow narrative names explicitly (a custody event's `released_at` is stamped when the holder lets go, and an SLA segment's `ended_at` and `business_minutes` are stamped when the segment closes); neither stamping increments a version counter, because these rows have none.

**Timestamp rendering — one uniform rule.** Every instant-valued field the server writes or echoes is rendered as an ISO 8601 UTC timestamp with exactly **three fractional-second digits** and a trailing `Z` — for example `2026-05-01T00:00:00.000Z`. This applies without exception to `created_at`, `updated_at`, `api_request_timestamp`, `published_at`, `quoted_at`, `submitted_at`, `tendered_at`, `decided_at`, `signed_at`, `booked_at`, `acquired_at`, `released_at`, `recorded_at`, `issued_at`, `deadline_at`, `responded_at`, `started_at`, `ended_at`, and the `current_utc` value the clock endpoint returns. It applies equally to caller-supplied instants: a client may send `starts_at` or `to_iso8601` with any legal ISO 8601 offset and any number of fractional digits, but the value is normalised to UTC and re-rendered with three fractional digits whenever the server echoes it back. Two instants are equal when they denote the same point in time, regardless of how the caller spelled them.

**Date rendering.** Fields that denote a calendar date rather than an instant — `travel_date`, `return_date`, `issue_date`, `expiry_date`, `taken_on`, `date_of_birth`, `scheduled_date`, `closure_date`, `effective_submission_date`, `projected_completion_date`, and the `deadline_date` reported by the feasibility read — are plain `YYYY-MM-DD` strings with no time component and no zone suffix.

**Nested path resolution.** Path segments are resolved strictly left to right. On any path rooted at an order, the order identifier is resolved first; a miss there is `ERR_ORDER_NOT_FOUND` (HTTP 404). Every other identifier — whether it appears later in the path or inside the request body as a foreign key — is resolved afterwards, also left to right, and a miss is `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Resource identifiers resolved by this second pass cover `Applicant`, `ServiceCatalogItem`, `Consulate`, `AgencyForm`, `AppointmentSlot`, `ApplicantDocument`, `PhotoAsset`, `PreparedForm`, `Appointment`, `CourierLeg`, `RFE` and `Shipment`. One non-obvious case belongs to the same rung: submitting a document for a `doc_type` for which the named applicant holds no slot is an `ERR_RESOURCE_NOT_FOUND`, not a validation failure.

### 2.5. The Logical Clock, the Business Calendar and Business-Minute Arithmetic

The server keeps a **logical clock**. Before any client sets it, the clock reads exactly `2026-05-01T00:00:00Z` — this is the fixed default instant, and the server must never fall back to the machine's wall-clock time for any evaluation. A `PlatformAdmin` moves the clock by supplying a `to_iso8601` instant to the clock-setting capability, which answers with the new `current_utc`. Every deadline, cutoff hour, lead-time test, validity window, business-day advance and `*_at` stamp in this specification reads the logical clock and nothing else.

**Business days.** A calendar date is a business day when its weekday falls in the set `MONDAY`, `TUESDAY`, `WEDNESDAY`, `THURSDAY`, `FRIDAY`, **and** — when a consulate participates in the evaluation — that date does not appear in the consulate's `closure_dates`. Saturdays and Sundays are never business days. Where a calculation is performed for an order whose `consulate_id` is set, the consulate participates and its closure calendar applies; where `consulate_id` is null, only the weekday test applies.

**Advancing by business days.** To advance a date `D` by `n` business days: first, while `D` is not itself a business day, step forward one calendar day at a time until it is. Then repeat `n` times: step forward exactly one calendar day, then keep stepping forward one calendar day at a time while the current date is not a business day. The date reached after the `n`-th repetition is the result. Advancing by zero business days therefore returns `D` itself when `D` is a business day, and the next business day on or after `D` when it is not.

**The business day window.** Business hours run from hour 9 to hour 17 UTC, so a full business day contains 480 business minutes. To count the business minutes between two instants `T1` and `T2`: walk every calendar date from the date of `T1` through the date of `T2` inclusive; skip any date that is not a business day; for each remaining date, take the later of `T1` and that date at 09:00:00Z as the lower bound and the earlier of `T2` and that date at 17:00:00Z as the upper bound, and when the upper bound is strictly after the lower bound, add the number of whole minutes between them. Fractions of a minute are truncated toward zero. The total is the business-minute count.

### 2.6. Two Non-Fungible Money Streams, Precision and Rounding

All money in this system is expressed in whole integer **cents** and is carried on one of two streams that are strictly non-fungible. The `GOVERNMENT` stream holds pass-through consular money: it is never discounted, never surcharged, never subject to the handling fee or its waiver, and — once it has been tendered to the agency — never returned. The `SERVICE` stream holds the expediter's own fee: it absorbs the tier surcharge, the multi-applicant discount, the handling fee, the split administration fee and the delivery escalation surcharge, and it is refundable on a sliding schedule. **No ledger row may move value from one stream to the other.**

Every money movement is recorded as an append-only `LedgerEntry` carrying `order_id`, `stream`, `kind`, a strictly positive `amount_cents`, a `reason` and a `recorded_at` instant. `stream` is either `GOVERNMENT` or `SERVICE`. `kind` is one of six values: `COLLECTION` brings customer money in; `TENDER` hands `GOVERNMENT` money to the agency; `EARN` recognises `SERVICE` money as revenue; `REFUND` returns money to the customer; and `TRANSFER_OUT` / `TRANSFER_IN` move already-held money from a parent order to a split child. `reason` is one of six named causes: `CUSTOMER_PAYMENT`, `AGENCY_TENDER`, `SERVICE_RECOGNITION`, `CANCELLATION_REFUND`, `REJECTION_REFUND`, `SPLIT_PARTITION`. Because `amount_cents` must be at least 1, a computed movement of zero cents writes no row at all.

**Precision and rounding.** Wherever a monetary computation produces a fractional cent it is rounded **half up** to a whole cent — a value ending in exactly half a cent rounds away from zero, upward. Percentages (`discount_pct_applied`, `promo_discount_pct`, the tier surcharge fractions and the refund fractions) are decimal fractions, not integer percentage points: a ten-percent discount is the number 0.10. The order in which rounding is applied relative to summation is **not** uniform across the calculations in this document, and each calculation that sums money states its own order explicitly; where a calculation pins round-per-line-then-sum, summing first and rounding once is expressly not the specified behaviour.

### 2.7. Single-Token Custody and the Agency-Custody Write Gate

The passport book is a single physical token. At every instant, exactly one party holds it, and `Order.custody_holder` names that party: `APPLICANT`, `SERVICE`, `COURIER` or `AGENCY`. Every handover is recorded as an append-only `CustodyEvent` carrying `order_id`, `holder_type`, an `acquired_at` instant, a `released_at` instant that is null for exactly one row per order, a `leg_index` that is populated only while a numbered courier leg is in flight and null otherwise, and a `reason` drawn from `ORDER_CREATED`, `LEG_DISPATCHED`, `LEG_DELIVERED`, `LEG_FAILED_RETURN`, `DECISION_RETURNED`, `SHIPMENT_DELIVERED`, `SHIPMENT_PICKED_UP`. Handing the book over always means the same two steps in the same order: stamp `released_at` on the currently open row with the logical clock, then append a new row whose `acquired_at` is that same instant.

**The agency-custody write gate.** While `Order.custody_holder` is `AGENCY`, the file is physically inside a government building and the expediter cannot alter it. Every mutating endpoint that touches that order or any of its descendants is therefore refused with `ERR_AGENCY_CUSTODY_LOCK` (HTTP 409), and this refusal is evaluated **early** — it pre-empts almost every substantive check in the ladder, so a request that would also have failed a state check, a cap check or a fiscal check reports the custody lock instead. The exclusion list is exhaustive and closed. The gate does **not** apply to:

- every `GET` endpoint in the system, without exception;
- `POST /expediting/orders/{id}/tender`;
- `POST /expediting/orders/{id}/rfes`;
- `POST /expediting/rfes/{id}/respond`;
- `POST /expediting/rfes/{id}/adjudicate`;
- `POST /expediting/orders/{id}/agency-decision`;
- `PATCH /expediting/shipments/{id}/address`;
- `POST /expediting/orders/{id}/cancel`;
- `POST /expediting/courier-legs/{id}/dispatch`;
- `POST /expediting/courier-legs/{id}/complete`;
- `POST /expediting/_clock/set_current_utc`.

Nothing else is excluded. In particular, recording a payment, changing the service level, changing the travel dates, submitting or resubmitting a document, uploading or retaking a photo, running a photo compliance check, preparing or signing a form, booking or rescheduling or recording the outcome of an appointment, creating a courier leg, creating a shipment, recording a delivery attempt, recording a pickup, splitting the order, quoting, accepting a quote, adding an applicant, acknowledging infeasibility and submitting are all blocked while the agency holds the book.

### 2.8. Optimistic Concurrency Control

Three write endpoints supersede state a client may not have observed, and each therefore requires the client to prove which version of a parent record it was looking at. In all three cases the supplied value is a **non-optional** request field, and a mismatch against the parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

1. **Preparing a form for an applicant.** `POST /expediting/applicants/{id}/prepared-forms` requires `expected_applicant_version`, carrying the client's last observed `version` of the target `Applicant`. A new preparation legitimately drives the applicant's prior preparation for the same `form_code` to `VOID`; a writer holding a stale view of the applicant would silently discard a preparation it never saw. If the applicant's `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
2. **Booking an appointment.** `POST /expediting/appointments` requires `expected_slot_version`, carrying the client's last observed `version` of the target `AppointmentSlot`. Capacity, `status` and `booked_count` all move with the slot's `version`, so a booking placed from a stale view could consume the last seat the client believed was free. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
3. **Changing the service level.** `POST /expediting/orders/{id}/service-level` requires `expected_order_version`, carrying the client's last observed `version` of the target `Order`. Once the order is in flight, a tier change is priced as a delta against the currently quoted amounts, so pricing that delta from a stale view of the order would charge the wrong difference. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. Rescheduling an appointment, completing a courier leg, adjudicating an evidence request, splitting an order and every other mutation in this specification are unguarded by optimistic concurrency control and must not require, or reject on, an `expected_*_version` field.

### 2.9. The Validation Priority Ladder

Every request is checked against a single, globally ordered ladder of 38 rungs. Checks run strictly in ascending rung order and **the first failing rung decides the response** — no later rung is evaluated once an earlier one has failed. This ordering is a contract in its own right: two defects in the same request must surface as the lower-numbered rung's error, and an implementation that reports the "more specific" failure first is wrong.

| Rung | Error | HTTP | What is checked, and where |
|---|---|---|---|
| 1 | `ERR_UNAUTHENTICATED` | 401 | `X-User-Role` is present and names one of the six declared roles; `X-User-ID` is present whenever the role is `CaseManager`, `Traveler`, `ComplianceOfficer`, `AgencyLiaison` or `CourierOps`. Applies to every endpoint. |
| 2 | `ERR_UNAUTHORIZED` | 403 | The acting role appears in the called endpoint's authorized-role list (§4). Applies to every endpoint. |
| 3 | `ERR_ORDER_NOT_FOUND` | 404 | An `{id}` segment naming an order resolves to a stored order. Applies to every path rooted at `/expediting/orders/{id}`. |
| 4 | `ERR_RESOURCE_NOT_FOUND` | 404 | Every other referenced resource resolves — path identifiers left to right, then body foreign keys left to right. Also owns the case where a document submission names a `doc_type` for which the applicant holds no slot. Applies to every endpoint carrying a resource id in the path or the body. |
| 5 | `ERR_NOT_ORDER_MEMBER` | 403 | When the acting role is `Traveler`, the targeted order carries an applicant whose `id` equals `X-User-ID`. Applies to every endpoint whose authorized-role list includes `Traveler`. |
| 6 | `ERR_VALIDATION` | 400 | Every required body field is present and of the declared type; numeric bounds hold; `limit` is between 1 and 100 and `offset` is at least 0; `return_date` is on or after `travel_date`; date and datetime fields parse as ISO 8601. Applies to every endpoint. |
| 7 | `ERR_INVALID_ENUM` | 422 | Every enum-typed request field on the closed list below carries a declared member. |
| 8 | `ERR_AGENCY_CUSTODY_LOCK` | 409 | The agency-custody write gate of §2.7. |
| 9 | `ERR_ORDER_TERMINAL` | 409 | The targeted order's `workflow_status` is not one of `COMPLETED`, `CANCELLED`, `ABANDONED`. Applies to every mutating endpoint touching an order or any of its descendants. |
| 10 | `ERR_INVALID_STATE` | 409 | The target resource sits in an admitted from-state for the requested transition (admitted sets below). |
| 11 | `ERR_STALE_VERSION` | 412 | The supplied `expected_applicant_version`, `expected_slot_version` or `expected_order_version` equals the OCC parent's current `version` (§2.8). |
| 12 | `ERR_SEGREGATION_OF_DUTIES` | 403 | On submission only, `X-User-ID` differs from the order's `quoted_by_user_id`. |
| 13 | `ERR_NATIONALITY_MISMATCH` | 422 | On adding an applicant, the applicant's `nationality_code` equals the `nationality_code` of the order's catalog item. |
| 14 | `ERR_CUSTODY_MISMATCH` | 409 | The passport is where the operation requires it (four scopes, below). |
| 15 | `ERR_LEG_SEQUENCE_VIOLATION` | 409 | On dispatch only, the leg carries the lowest `leg_index` among the order's legs whose `leg_status` is `CREATED` or `FAILED`. |
| 16 | `ERR_EMBASSY_CLOSED` | 409 | The date the operation lands on is a business day and is not in the consulate's `closure_dates`. |
| 17 | `ERR_OUT_OF_JURISDICTION` | 422 | The applicant's `residence_region_code` is in the target slot's consulate's `jurisdiction_region_codes`, and that consulate is the order's `consulate_id`. |
| 18 | `ERR_LEAD_TIME_VIOLATION` | 422 | The target slot's `starts_at` is at least 48 hours after the logical clock. |
| 19 | `ERR_SLOT_CAPACITY_EXCEEDED` | 409 | The target slot's `booked_count` is strictly less than its `capacity`. |
| 20 | `ERR_RESCHEDULE_CAP_EXCEEDED` | 409 | On reschedule only: from `BOOKED`, `reschedule_count` is below 2; from `NO_SHOW`, `no_show_count` is below 2. |
| 21 | `ERR_RESUBMISSION_CAP_EXCEEDED` | 409 | On resubmit only, `resubmission_count` is below 2. |
| 22 | `ERR_DOCUMENT_VALIDITY_INSUFFICIENT` | 422 | On an accept decision only, the document validity check returns valid against the order's `travel_date` and `return_date`. |
| 23 | `ERR_PHOTO_RETAKE_CAP_EXCEEDED` | 409 | On retake only, `retake_count` is below 3. |
| 24 | `ERR_FORM_REVISION_STALE` | 409 | On preparing a form only, the named `AgencyForm` has `status` `ACTIVE` and its `form_code` equals the order's catalog item's `form_code`. |
| 25 | `ERR_COURIER_ATTEMPT_CAP_EXCEEDED` | 409 | On dispatch only, the leg's `attempt_count` is below 3 (that is, fewer than 3 dispatch attempts so far). |
| 26 | `ERR_DELIVERY_ATTEMPT_CAP_EXCEEDED` | 409 | On a delivery attempt only, the shipment's `attempt_count` is below 3 **and** the shipment is not already `HELD_FOR_PICKUP`. |
| 27 | `ERR_RFE_ROUND_CAP_EXCEEDED` | 409 | On issuing an evidence request only, the order's `rfe_round_count` is below 2. |
| 28 | `ERR_RFE_DEADLINE_PASSED` | 409 | On responding only, the logical clock is at or before the evidence request's `deadline_at`. Exact equality passes. |
| 29 | `ERR_TIER_NOT_AN_UPGRADE` | 422 | On a service-level change only, the requested `service_level` is strictly higher than the current one in the order `STANDARD` below `EXPEDITED` below `RUSH`. |
| 30 | `ERR_UPGRADE_STAGE_CLOSED` | 409 | On a service-level change only, `workflow_status` is in the set `DRAFT`, `QUOTED`, `INTAKE`, `READY_FOR_SUBMISSION`. |
| 31 | `ERR_STREAM_ALLOCATION_INVALID` | 422 | On a payment only, after applying `stream_override` the order's `collected_government_cents` does not exceed its `government_fee_quoted_cents`. |
| 32 | `ERR_APPLICANT_NOT_READY` | 409 | On a split only, every applicant named in `applicant_ids` belongs to this order and has `readiness_status` `COMPLETE`, and at least one applicant remains on the parent. |
| 33 | `ERR_SPLIT_PARTITION_MISMATCH` | 422 | On a split only, when `transfer_cents_override` is supplied it equals the computed transfer total. |
| 34 | `ERR_REQUIRED_DOCUMENTS_INCOMPLETE` | 409 | On submission only, every applicant of the order whose `readiness_status` is `PENDING` or `COMPLETE` is `COMPLETE`. |
| 35 | `ERR_RUSH_CUTOFF_MISSED` | 409 | On submission only, when `service_level` is `RUSH`, the logical clock hour is strictly below 15 and the current date is a business day. |
| 36 | `ERR_TRAVEL_DATE_INFEASIBLE` | 409 | On submission only, `feasibility_status` is `FEASIBLE` or `ACKNOWLEDGED_INFEASIBLE`. |
| 37 | `ERR_BALANCE_OUTSTANDING` | 402 | On submission only, `outstanding_cents` is at least `total_quoted_cents`. |
| 38 | `ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED` | 422 | On cancellation only, when `custody_holder` is `AGENCY`, the request carries `acknowledge_government_fee_forfeit` set to true. |

#### 2.9.1. Rung 7 — the closed enum-routing list

`ERR_INVALID_ENUM` (HTTP 422) is owned by **exactly** the following request fields and no others. For each, the declared member set is given; a value outside that set routes to `ERR_INVALID_ENUM`.

- `service_level` on order creation and on a service-level change — `STANDARD`, `EXPEDITED`, `RUSH`.
- `visa_type` on catalog-item creation — `TOURIST`, `BUSINESS`, `STUDENT`, `PASSPORT_RENEWAL`, `PASSPORT_FIRST_TIME`.
- `government_fee_basis` on catalog-item creation — `PER_APPLICANT`, `PER_ORDER`.
- `doc_type` on document-requirement creation — `PASSPORT_BOOK`, `PROOF_OF_TRAVEL`, `INVITATION_LETTER`, `BANK_STATEMENT`, `VACCINATION_CERT`, `EMPLOYMENT_LETTER`, `PARENTAL_CONSENT`.
- `validity_rule` on document-requirement creation — `NONE`, `EXPIRES_AFTER_ISSUE_DAYS`, `VALID_BEYOND_RETURN_MONTHS`.
- `doc_type` on document submission — the same seven document classes listed above.
- `background_code` on photo upload and on retake — `WHITE`, `OFF_WHITE`, `COLORED`.
- `from_holder` on courier-leg creation — `APPLICANT`, `SERVICE`, `AGENCY`.
- `to_holder` on courier-leg creation — `SERVICE`, `AGENCY`, `APPLICANT`.
- `method` on shipment creation — `GROUND`, `OVERNIGHT`, `COURIER_SAME_DAY`.
- `requested_doc_type` on issuing an evidence request — the same seven document classes.
- `decision` on document review — `ACCEPT`, `REJECT`.
- `outcome` on courier-leg completion — `DELIVERED`, `FAILED`.
- `outcome` on recording an appointment outcome — `ATTENDED`, `NO_SHOW`.
- `outcome` on evidence-request adjudication — `CLEARED`, `INSUFFICIENT`, `EXPIRED`.
- `decision` on the agency decision — `APPROVED`, `REJECTED`.
- `stream_override` on a payment — `GOVERNMENT`, `SERVICE`.

**No other field routes to `ERR_INVALID_ENUM`.** Every other malformed value — of any type, on any endpoint — routes to `ERR_VALIDATION` at rung 6. Two consequences deserve naming because they are easy to get wrong. First, the `outcome` field on a **shipment delivery attempt** is deliberately absent from the list above: a value there outside `DELIVERED` and `FAILED` is an `ERR_VALIDATION`, not an `ERR_INVALID_ENUM`. Second, enum-valued **query filters** (`workflow_status`, `status`, `prep_status`, `readiness_status`, `review_status`, `compliance_status`, `booking_status`, `leg_status`, `rfe_status`, `stream`, `kind`) are not request-body fields and route to neither error; per §2.3 an off-enum filter value simply returns an empty page.

#### 2.9.2. Rung 10 — admitted from-states, endpoint by endpoint

Rung 10 asks one question: is the target resource in a state from which the requested transition is declared? The admitted sets are exact; anything else is `ERR_INVALID_STATE` (HTTP 409).

- **Quote (and re-quote):** the order's `workflow_status` is `DRAFT` or `QUOTED`.
- **Accept quote:** `workflow_status` is `QUOTED`, `payment_status` is `COLLECTED`, and `total_quoted_cents` is strictly greater than 0.
- **Payment:** `payment_status` is `UNPAID` or `PARTIALLY_COLLECTED`, and `total_quoted_cents` is strictly greater than 0. A payment against an order already at `COLLECTED`, `REFUND_PENDING`, `PARTIALLY_REFUNDED` or `REFUNDED`, or against an unpriced order, is `ERR_INVALID_STATE`.
- **Submission:** `workflow_status` is `INTAKE` or `READY_FOR_SUBMISSION`. Both are admitted here on purpose — an `INTAKE` order that is genuinely not ready must fall through to rung 34 and report `ERR_REQUIRED_DOCUMENTS_INCOMPLETE`, not be masked by a state error.
- **Split:** `workflow_status` is `INTAKE` or `READY_FOR_SUBMISSION`.
- **Cancellation:** `workflow_status` is one of `DRAFT`, `QUOTED`, `INTAKE`, `READY_FOR_SUBMISSION`, `SUBMITTED`, `AT_AGENCY`. Cancellation is **not** declared from `RFE_PENDING`, `APPROVED`, `REJECTED` or `DELIVERING`, and an attempt from any of those four is `ERR_INVALID_STATE`.
- **Tender:** `workflow_status` is `SUBMITTED`.
- **Issuing an evidence request:** `workflow_status` is `AT_AGENCY`.
- **Responding to an evidence request:** the request's `rfe_status` is `OPEN`.
- **Adjudicating an evidence request:** for outcome `CLEARED` and for outcome `INSUFFICIENT`, `rfe_status` is `RESPONDED`; for outcome `EXPIRED`, `rfe_status` is `OPEN`.
- **Agency decision:** `workflow_status` is `AT_AGENCY`.
- **Compliance acknowledgment:** `feasibility_status` is `INFEASIBLE` and `workflow_status` is `INTAKE` or `READY_FOR_SUBMISSION`.
- **Creating a shipment:** `workflow_status` is `APPROVED` or `REJECTED`.
- **Delivery attempt:** `delivery_status` is `CREATED` or `OUT_FOR_DELIVERY`. A shipment already `DELIVERED` or `PICKED_UP` is `ERR_INVALID_STATE`; a shipment at `HELD_FOR_PICKUP` is **not** owned by this rung and falls through to rung 26.
- **Pickup:** `delivery_status` is `HELD_FOR_PICKUP`.
- **Document submission:** the slot's `review_status` is `MISSING`.
- **Document review:** `review_status` is `RECEIVED`.
- **Document resubmission:** `review_status` is `REJECTED`.
- **Photo compliance check:** `compliance_status` is `PENDING`.
- **Photo retake:** `compliance_status` is `FAILED` or `EXPIRED`.
- **Signing a prepared form:** `prep_status` is `PREPARED`.
- **Courier-leg dispatch:** `leg_status` is `CREATED` or `FAILED`.
- **Courier-leg completion:** `leg_status` is `DISPATCHED`.
- **Appointment reschedule:** `booking_status` is `BOOKED` or `NO_SHOW`.
- **Appointment outcome:** `booking_status` is `BOOKED`, and the logical clock is at or after the slot's `starts_at`. An outcome recorded before the interview window opens is `ERR_INVALID_STATE`.

Four cases are deliberately **not** owned by rung 10, and an implementation must not fold them back in: the target slot's status on appointment booking (owned by rungs 16 and 19), submission attempted from `INTAKE` (owned by rung 34), a delivery attempt on a `HELD_FOR_PICKUP` shipment (owned by rung 26), and the workflow gate on a service-level change (owned by rung 30). Two further endpoints carry no state gate at all and are reached by rung 10 without a check: changing the travel dates, and changing a shipment's delivery region.

#### 2.9.3. Rungs scoped to one verb of a paired operation

Several rungs are attached to exactly one member of a pair of similar-looking operations. The scoping is deliberate and must not be generalised to the sibling.

- Rung 12 (`ERR_SEGREGATION_OF_DUTIES`) guards **submission** only. Quoting, re-quoting and accepting a quote impose no duty separation whatsoever; the same `X-User-ID` may quote and re-quote an order without limit.
- Rung 15 (`ERR_LEG_SEQUENCE_VIOLATION`) and rung 25 (`ERR_COURIER_ATTEMPT_CAP_EXCEEDED`) guard **dispatch** only, never completion. A leg may be completed regardless of ordering or attempt count once it is `DISPATCHED`.
- Rung 20 (`ERR_RESCHEDULE_CAP_EXCEEDED`) guards **reschedule** only, never the original booking. A first booking consumes no reschedule allowance.
- Rung 22 (`ERR_DOCUMENT_VALIDITY_INSUFFICIENT`) guards the **accept** branch of document review only. A reject decision never runs the validity check, and rung 21 (`ERR_RESUBMISSION_CAP_EXCEEDED`) guards **resubmit** only, never the original submission into a `MISSING` slot.
- Rung 24 (`ERR_FORM_REVISION_STALE`) guards **preparing** a form only, never signing one. Signing has its own requirement, that the referenced revision still be `ACTIVE`, which is a state condition on the preparation rather than this rung.
- Rung 26 (`ERR_DELIVERY_ATTEMPT_CAP_EXCEEDED`) guards **delivery attempts** only, never the pickup that closes a held shipment.
- Rung 28 (`ERR_RFE_DEADLINE_PASSED`) guards **responding** to an evidence request only, never adjudicating one — indeed adjudication with outcome `EXPIRED` requires the deadline to have passed.
- Rung 31 (`ERR_STREAM_ALLOCATION_INVALID`) guards **payments** only, never refunds or transfers.
- Rung 38 (`ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED`) guards **cancellation** only, never an agency rejection or an abandonment, both of which forfeit the government fee without any acknowledgment field.
- Rungs 34 through 37 (`ERR_REQUIRED_DOCUMENTS_INCOMPLETE`, `ERR_RUSH_CUTOFF_MISSED`, `ERR_TRAVEL_DATE_INFEASIBLE`, `ERR_BALANCE_OUTSTANDING`) all guard **submission** only. None of them applies to tender, to the agency decision, or to any other order transition.

#### 2.9.4. Rung 14 — the four custody scopes

`ERR_CUSTODY_MISMATCH` (HTTP 409) is checked on exactly four operations, each with its own required holder: on **courier-leg dispatch**, the leg's `from_holder` must equal the order's `custody_holder`; on **shipment creation**, `custody_holder` must be `SERVICE`; on the **first delivery attempt** of a shipment, `custody_holder` must be `SERVICE`; on **tender**, `custody_holder` must be `AGENCY`. No other endpoint reports this error.

#### 2.9.5. Rung 16 — the two closure scopes

`ERR_EMBASSY_CLOSED` (HTTP 409) covers exactly two kinds of landing date. On **courier-leg dispatch**, the leg's `scheduled_date` must be a business day and must not appear in the order consulate's `closure_dates`. On **appointment booking and reschedule**, the calendar date of the target slot's `starts_at` must be a business day and must not appear in that consulate's `closure_dates` — equivalently, the slot's `status` must not be `CLOSED`.

### 2.10. The Version-Bump Ledger

Because several operations in this system mutate three, four or five rows at once, the rule for how `version` moves must be stated per operation rather than left to inference.

**The general rule.** A request increments a row's `version` by exactly **1**, and sets that row's `updated_at` to the logical clock, when and only when the request changes at least one persisted value on that row. The number of fields changed is irrelevant — five field changes on one row in one request is still a single increment. A row that a request merely reads, or whose recomputation produces the value it already held, is not bumped and its `updated_at` does not move. Newly created rows are born at `version` 1 and are not additionally bumped by the request that created them. The four append-only entities (`DocumentRequirement`, `CustodyEvent`, `LedgerEntry`, `SlaSegment`) have no `version` and are never counted in this ledger, even when a request stamps a custody event's `released_at` or an SLA segment's `ended_at` and `business_minutes`.

**The per-operation ledger.** Each row below names the rows a successful request touches and how many times each is bumped.

| Operation | Rows bumped (+1 each unless stated) | Rows explicitly NOT bumped |
|---|---|---|
| Create catalog item | the new `ServiceCatalogItem` is born at version 1 | — |
| Add a document requirement | none — `DocumentRequirement` carries no version | the parent `ServiceCatalogItem` |
| Register an agency form revision | the new `AgencyForm` is born at version 1 | — |
| Publish an agency form revision | the published `AgencyForm`; the prior `ACTIVE` revision of that `form_code`, when one exists; every `PreparedForm` driven to `STALE`; every `Applicant` driven `COMPLETE` → `PENDING`; every `Order` driven `READY_FOR_SUBMISSION` → `INTAKE`; every `CourierLeg` driven `CREATED` → `CANCELLED` | preparations already `VOID` or already `STALE`; applicants already `PENDING` or `WITHDRAWN`; orders in any status other than `READY_FOR_SUBMISSION`; legs in `DISPATCHED`, `FAILED`, `DELIVERED` or `CANCELLED`; when no prior revision was `ACTIVE`, nothing beyond the published row moves |
| Create a consulate | the new `Consulate` is born at version 1 | — |
| Add a closure date | the `Consulate`; every `AppointmentSlot` of that consulate whose `starts_at` falls on the added date | slots on any other date |
| Publish a slot | the new `AppointmentSlot` is born at version 1 | the owning `Consulate` |
| Open an order | the new `Order` is born at version 1 | — |
| Add an applicant | the new `Applicant` and each new `ApplicantDocument` slot are born at version 1; the `Order` (its `applicant_count` moved) | the `ServiceCatalogItem`; the `Consulate` |
| Quote / re-quote | the `Order` | every `Applicant` — quoting never recomputes readiness |
| Accept the quote | the `Order`; each `Applicant` whose `readiness_status` actually changes | applicants whose readiness recomputes to the value they already held |
| Record a payment | the `Order` | nothing else; the one or two new `LedgerEntry` rows carry no version |
| Change the service level | the `Order`, exactly once, however many of `service_fee_quoted_cents`, `total_quoted_cents`, `payment_status`, `projected_completion_date` and `feasibility_status` move | every child row |
| Change the travel dates | the `Order`; every `ApplicantDocument` driven `ACCEPTED` → `RECEIVED`; every `PhotoAsset` driven `PASSED` → `EXPIRED`; each `Applicant` whose readiness changes; every `CourierLeg` cancelled by a consequent regression | documents whose `validity_rule` is `NONE`; documents in any state other than `ACCEPTED`; photos whose validity window still covers the new `travel_date`; photos not in `PASSED` |
| Acknowledge infeasibility | the `Order` | — |
| Submit | the `Order` | every child row; the new `LedgerEntry` and `SlaSegment` carry no version |
| Split | the parent `Order`; each moved `Applicant` (its `order_id` changed); the child `Order` is born at version 1 | the moved applicants' `ApplicantDocument`, `PhotoAsset`, `PreparedForm` and `Appointment` rows — they key off `applicant_id`, which does not change; applicants left on the parent |
| Cancel | the `Order`; every `Applicant` driven to `WITHDRAWN`; every `Appointment` driven `BOOKED` → `CANCELLED`; every `AppointmentSlot` whose `booked_count` drops; every `CourierLeg` driven from `CREATED` or `FAILED` to `CANCELLED` | applicants already `WITHDRAWN`; appointments in `ATTENDED`, `NO_SHOW` or `CANCELLED`; legs in `DISPATCHED` or `DELIVERED` |
| Tender | the `Order` | — |
| Submit a document into its slot | the `ApplicantDocument` | the `Applicant` — a slot moving `MISSING` → `RECEIVED` cannot change readiness; the `Order` |
| Review a document | the `ApplicantDocument`; the `Applicant` when `accepted_doc_count` or `readiness_status` moves; the `Order` when it consequently advances `INTAKE` → `READY_FOR_SUBMISSION` | on a reject decision against an optional slot, neither the `Applicant` nor the `Order` moves |
| Resubmit a document | the `ApplicantDocument` | the `Applicant`; the `Order` |
| Upload a photo | the new `PhotoAsset` is born at version 1 | the `Applicant` |
| Run a photo compliance check | the `PhotoAsset`; the `Applicant` when readiness moves; the `Order` when it consequently advances | on a `FAILED` verdict for an applicant already `PENDING`, only the photo moves |
| Retake a photo | the source `PhotoAsset` (driven to `SUPERSEDED`); the new `PhotoAsset` is born at version 1; the `Applicant` when readiness moves | the `Order` unless it regresses |
| Prepare a form | the new `PreparedForm` is born at version 1; the superseded prior `PreparedForm` of the same `form_code`, when one exists; the `Applicant` — always, exactly once | the `Order` unless it advances or regresses; when the applicant had no prior preparation of that `form_code`, no supersession bump occurs |
| Sign a prepared form | the `PreparedForm` | the `Applicant` — a `PREPARED` form already satisfies readiness, so signing changes nothing there |
| Book an appointment | the new `Appointment` is born at version 1; the target `AppointmentSlot` | the `Applicant`; the `Order` |
| Reschedule an appointment | the `Appointment`; the target `AppointmentSlot`; and, only when the booking was `BOOKED`, the released `AppointmentSlot` | on a rebook out of `NO_SHOW` no slot is released, so exactly one slot is bumped |
| Record an appointment outcome | the `Appointment`; on `NO_SHOW` the `AppointmentSlot`; the `Applicant` when readiness moves; the `Order` when it consequently advances or regresses | on `ATTENDED` the slot is **not** bumped — an attended booking stays inside the counted set, so `booked_count` does not move |
| Create a courier leg | the new `CourierLeg` is born at version 1 | the `Order` |
| Dispatch a leg | the `CourierLeg`; the `Order` (its `custody_holder` moved to `COURIER`) | — |
| Complete a leg | the `CourierLeg`; the `Order` (its `custody_holder` moved); each `Applicant` whose readiness changes | applicants whose readiness is unchanged |
| Issue an evidence request | the new `RFE` is born at version 1; the `Order` | — |
| Respond to an evidence request | the `RFE` | the `Order` — responding leaves every order field untouched |
| Adjudicate an evidence request | the `RFE`; the `Order` on outcome `CLEARED` and on an abandoning outcome; on an abandoning outcome the newly created return `CourierLeg` is born at version 1 | on outcome `INSUFFICIENT` **below** the round cap, the `RFE` alone is bumped — the order stays in `RFE_PENDING` with no field change and is **not** bumped |
| Agency decision | the `Order`; the newly created return `CourierLeg` is born at version 1; on a rejection, every `Applicant` driven to `WITHDRAWN`, every `Appointment` driven to `CANCELLED` and every `AppointmentSlot` whose `booked_count` drops | on an approval, no applicant, appointment or slot moves |
| Create a shipment | the new `Shipment` is born at version 1; the `Order` | — |
| Record a delivery attempt | the `Shipment`; the `Order` only when its `custody_holder` or `workflow_status` moves | a repeat `FAILED` attempt from `OUT_FOR_DELIVERY`, and the `FAILED` attempt that lands on `HELD_FOR_PICKUP`, change nothing on the order and do **not** bump it |
| Change a shipment address | the `Shipment` | the `Order` |
| Record a pickup | the `Shipment`; the `Order` | — |
| Set the logical clock | none | every entity row in the system |

### 2.11. The Four Conservation Invariants

Four arithmetic identities must hold at every instant, and three of them are surfaced by computed reads so they can be audited.

**Invariant 1 — money conservation.** For every order, at every instant:

> `collected_cents` equals `government_tendered_cents` plus `service_earned_cents` plus `refunded_cents` plus `outstanding_cents`.

`collected_cents` is the sum of `collected_government_cents` and `collected_service_cents`. Each per-stream collected figure is the sum of `amount_cents` over that order's ledger rows of that stream with `kind` `COLLECTION`, **minus** that stream's `TRANSFER_OUT` rows, **plus** that stream's `TRANSFER_IN` rows. `government_tendered_cents` is the sum of `amount_cents` over `GOVERNMENT`-stream rows with `kind` `TENDER`. `service_earned_cents` is the sum over `SERVICE`-stream rows with `kind` `EARN`. `refunded_cents` is the sum over rows of either stream with `kind` `REFUND`. `outstanding_cents` is customer money the expediter still holds — money neither released to the agency, nor recognised as revenue, nor returned. The computed read reports `conservation_ok` as true exactly when the identity holds with zero tolerance in whole cents.

**Invariant 1a — the per-stream allocation ceiling.** Two further inequalities hold on the `GOVERNMENT` stream alone: `collected_government_cents` is at least `government_tendered_cents`, and `collected_government_cents` never exceeds `government_fee_quoted_cents`. The second of these is the breakable half. The ordinary payment waterfall fills the government bucket only up to its remaining need and can therefore never overshoot; the optional `stream_override` field is the single mechanism capable of pushing `collected_government_cents` past `government_fee_quoted_cents`, and that attempt is refused at rung 31 with `ERR_STREAM_ALLOCATION_INVALID`.

**Invariant 1b — the pinned refund draw.** When a refund of a given amount is actually disbursed on a stream, it is funded by a fixed two-step waterfall, applied per stream and in this order. First, take the smaller of the refund amount and the order's current `outstanding_cents`, and subtract that amount from `outstanding_cents`. Second, subtract whatever remains of the refund from `service_earned_cents` — this de-recognises revenue the expediter had already booked. Finally add the full refund amount to `refunded_cents`. Because the two subtractions together equal the addition, Invariant 1 survives the draw exactly. The `GOVERNMENT` stream is **never** drawn from `government_tendered_cents`: once pass-through money is with the agency it is unreachable, which is precisely why a post-tender refund returns zero on that stream. Note the tension this creates with the plain-language description of `outstanding_cents` as a running balance that every `REFUND` decrements: the waterfall above governs, and a refund larger than the outstanding balance takes its remainder from `service_earned_cents` rather than driving `outstanding_cents` negative.

**Invariant 2 — custody cardinality.** For every order, exactly **one** `CustodyEvent` row has `released_at` null; that single open row's `holder_type` equals the order's `custody_holder`; and no two custody events of the same order have overlapping intervals, where an interval runs from `acquired_at` inclusive to `released_at` exclusive. The computed summary reports `open_custody_count` (which must be 1) and `open_custody_holder`.

**Invariant 3 — the SLA time partition.** Let the order's `SlaSegment` rows be taken in `started_at` ascending order. The first segment's `started_at` equals the order's `submitted_at`. For every adjacent pair, the earlier segment's `ended_at` equals the later segment's `started_at` — no gaps, no overlaps. The last segment's `ended_at` equals the order's `decided_at` when a decision has been recorded, and is null (the segment is open) when one has not. The sum of `business_minutes` over all **closed** segments equals the business minutes between `submitted_at` and `decided_at` computed in one shot. And the sum of `business_minutes` over the `RUNNING` segments equals the contractual clock-stop SLA figure. Because the segments tile the interval exactly, the running total plus the paused total equals the gross total at every instant.

**Invariant 4 — the split partition.** A split never creates or destroys money. Every `TRANSFER_OUT` row written on the parent has a mirror `TRANSFER_IN` row on the child with an identical `stream` and an identical `amount_cents`, so the two orders' `collected_cents` figures together equal what the parent alone held before the split. The two streams are partitioned independently and are never netted against each other. The parent's split administration charge is not a transfer: it is a `SERVICE`-stream `EARN` row that moves money from the parent's `outstanding_cents` into its `service_earned_cents` without changing either order's `collected_cents`.

### 2.12. Response-Field Projections and Formula Intermediates

Each entity serialises a fixed set of fields. Alongside its own attributes, every row carries `id` and `created_at`; the thirteen versioned entities additionally carry `updated_at` and `version`, and the four append-only entities carry neither.

- **`ServiceCatalogItem`** — `nationality_code`, `destination_country`, `visa_type`, `government_fee_cents`, `government_fee_basis`, `base_service_fee_cents`, `agency_turnaround_override_days`, `form_code`, `requires_appointment`.
- **`DocumentRequirement`** — `catalog_item_id`, `doc_type`, `is_required`, `validity_rule`, `validity_param`, `applies_max_age_years`.
- **`AgencyForm`** — `form_code`, `revision`, `required_field_count`, `status`, `published_at`.
- **`Consulate`** — `name`, `destination_country`, `jurisdiction_region_codes`, `closure_dates`.
- **`AppointmentSlot`** — `consulate_id`, `starts_at`, `capacity`, `booked_count`, `status`.
- **`Order`** — `catalog_item_id`, `consulate_id`, `parent_order_id`, `service_level`, `travel_date`, `return_date`, `delivery_region_code`, `workflow_status`, `payment_status`, `custody_holder`, `feasibility_status`, `furthest_stage_reached`, `applicant_count`, `government_fee_quoted_cents`, `service_fee_quoted_cents`, `total_quoted_cents`, `discount_pct_applied`, `handling_fee_waived`, `collected_government_cents`, `collected_service_cents`, `collected_cents`, `government_tendered_cents`, `service_earned_cents`, `refunded_cents`, `refund_scheduled_cents`, `outstanding_cents`, `quoted_by_user_id`, `submitted_by_user_id`, `acknowledged_by_user_id`, `quoted_at`, `submitted_at`, `tendered_at`, `decided_at`, `effective_submission_date`, `projected_completion_date`, `rfe_round_count`.
- **`Applicant`** — `order_id`, `full_name`, `date_of_birth`, `nationality_code`, `residence_region_code`, `readiness_status`, `age_years`, `required_doc_count`, `accepted_doc_count`.
- **`ApplicantDocument`** — `applicant_id`, `doc_type`, `is_required`, `validity_rule`, `validity_param`, `review_status`, `issue_date`, `expiry_date`, `resubmission_count`, `rejection_reason`, `reviewed_by_user_id`.
- **`PhotoAsset`** — `applicant_id`, `taken_on`, `head_height_ratio`, `background_code`, `resolution_px`, `compliance_status`, `retake_count`, `failure_reasons`.
- **`PreparedForm`** — `applicant_id`, `agency_form_id`, `form_code`, `revision_used`, `filled_field_count`, `prep_status`, `signed_at`, `signed_by_user_id`.
- **`Appointment`** — `applicant_id`, `slot_id`, `booking_status`, `reschedule_count`, `no_show_count`, `booked_at`.
- **`CourierLeg`** — `order_id`, `leg_index`, `from_holder`, `to_holder`, `scheduled_date`, `leg_status`, `attempt_count`.
- **`CustodyEvent`** — `order_id`, `holder_type`, `leg_index`, `acquired_at`, `released_at`, `reason`.
- **`RFE`** — `order_id`, `round_index`, `requested_doc_type`, `issued_at`, `deadline_at`, `rfe_status`, `responded_at`, `response_count`.
- **`LedgerEntry`** — `order_id`, `stream`, `kind`, `amount_cents`, `reason`, `recorded_at`.
- **`Shipment`** — `order_id`, `method`, `address_region_code`, `signature_required`, `delivery_status`, `attempt_count`, `escalation_fee_cents`.
- **`SlaSegment`** — `order_id`, `segment_kind`, `cause`, `started_at`, `ended_at`, `business_minutes`.

**Three computed reads** return purpose-built shapes rather than an entity. The feasibility read returns exactly `effective_submission_date`, `agency_turnaround_days`, `projected_completion_date`, `deadline_date`, `feasibility_status` and `variant_used`. The requirement read returns exactly `required_doc_types`, `optional_doc_types`, `required_doc_count`, `accepted_doc_count` and `satisfied`. The order summary returns exactly `collected_cents`, `government_tendered_cents`, `service_earned_cents`, `refunded_cents`, `refund_scheduled_cents`, `outstanding_cents`, `conservation_ok`, `open_custody_count`, `open_custody_holder`, `sla_running_business_minutes`, `sla_paused_business_minutes` and `sla_gross_business_minutes`. The clock capability returns exactly `current_utc`.

**Formula intermediates are never serialised.** The following quantities exist only inside calculations and appear on no response body anywhere in the system: the per-tier surcharge fraction; a per-applicant raw line amount, its post-discount value, and the rounded per-line amount; the service subtotal before the handling component; the automatic multi-applicant discount fraction before it is combined and capped; the handling component itself; the remaining government need used by the payment waterfall and the two per-stream parts it produces; the stage refund fraction and the per-stream refund amounts; the amount drawn from the outstanding balance and the remainder drawn from earned revenue; the new and old subtotals and the delta used to price an in-flight tier change; the number of whole calendar days to the travel date used by the delivery escalation test; the intermediate dates used to walk a projection forward; the consumed and remaining turnaround days; the moved applicant count and the parent's pre-move applicant count; the two per-stream transfer amounts and their sum; the split administration charge; the derived and required document sets themselves (only their sizes and the type lists on the requirement read are exposed); and the ordered failure list before it is written to `failure_reasons`. Note in particular that `agency_turnaround_days`, `deadline_date` and `variant_used` are **not** attributes of `Order` — they exist only on the feasibility read — while `effective_submission_date` and `projected_completion_date` are genuine stored order attributes that the feasibility read echoes.

---

## 3. Business Logic & Workflows

### 3.1. Configuring the Product Catalogue and Its Paperwork

Nothing can be ordered until a `PlatformAdmin` has described the product. A **catalog item** is a configuration row keyed by the triple of the applicant's citizenship, the destination country and the product being bought: `nationality_code` and `destination_country` are each exactly two uppercase letters, and `visa_type` names the product as one of `TOURIST`, `BUSINESS`, `STUDENT`, `PASSPORT_RENEWAL` or `PASSPORT_FIRST_TIME`. The row carries the two prices that drive everything downstream — `government_fee_cents`, the pass-through consular charge, and `base_service_fee_cents`, the expediter's own fee per traveller, both of which must be at least 0 — plus `government_fee_basis`, which is either `PER_ORDER` (one consular charge for the whole file) or `PER_APPLICANT` (one charge per traveller). Two optional settings complete the row. `agency_turnaround_override_days`, when supplied, must be at least 1 and replaces the tier's default turnaround assumption entirely; when omitted it is stored as null. `requires_appointment` defaults to false, and when true it makes an attended consular interview a hard precondition of submission for every traveller on the order. Finally, `form_code` names the government form that every traveller on an order of this product must have prepared.

Under each catalog item sit its **document requirement lines**. A requirement carries `catalog_item_id`, a `doc_type` drawn from `PASSPORT_BOOK`, `PROOF_OF_TRAVEL`, `INVITATION_LETTER`, `BANK_STATEMENT`, `VACCINATION_CERT`, `EMPLOYMENT_LETTER` and `PARENTAL_CONSENT`, and an `is_required` flag. Only lines with `is_required` true gate submission; a line with `is_required` false still produces a document slot on every eligible traveller, but that slot never holds anything up. The `validity_rule` says which window a reviewer must evaluate: `NONE` means no dates are consulted at all, `EXPIRES_AFTER_ISSUE_DAYS` measures a window forward from the document's issue date, and `VALID_BEYOND_RETURN_MONTHS` measures a window forward from the traveller's return date. `validity_param` supplies the number for that rule — days for the issue-anchored rule, months for the return-anchored rule, ignored entirely for `NONE`, and when supplied it must be at least 1. Omitting `validity_param` is normal and the stored default depends on the rule: a `VALID_BEYOND_RETURN_MONTHS` line stores **6 months**, and an `EXPIRES_AFTER_ISSUE_DAYS` line stores **90 days**. A line whose `validity_rule` is `NONE` stores null.

Age gating lives on the same row. `applies_max_age_years`, when supplied, must be at least 1, and narrows a requirement to travellers whose computed age in whole years is **strictly less** than the stored number; a line whose `applies_max_age_years` is null applies at every age. The default is deliberately asymmetric: omitting the field on a `PARENTAL_CONSENT` line stores **16**, the minor-age threshold, so parental consent is demanded of travellers aged 15 and under and never of a 16-year-old; omitting it on any other document class stores null. An operator who wants a differently-shaped age gate must state the number explicitly.

Government forms are versioned independently of the catalogue. A `PlatformAdmin` registers a revision by supplying `form_code`, a `revision` number of at least 1, and `required_field_count`, the number of fields at least 1 that a traveller's preparation must have filled for that revision to be accepted. A newly registered revision has `status` `DRAFT` and a null `published_at`.

### 3.2. Publishing a Form Revision and the Five-Hop Staleness Cascade

Publishing is the single most disruptive operation in the system, and it is a `PlatformAdmin` capability. A `DRAFT` revision moves `DRAFT → ACTIVE` and its `published_at` is stamped with the logical clock, provided that no other revision of the same `form_code` with a strictly higher `revision` number already holds `status` `ACTIVE`. Publishing then walks a five-hop transitive cascade in which each hop is caused by the hop before it, not by the original request.

**Hop 1.** The revision of the same `form_code` that currently holds `status` `ACTIVE` — if there is one — moves `ACTIVE → SUPERSEDED`. If no revision of that `form_code` was `ACTIVE`, this hop does not fire and none of the four hops below fire either; the newly published revision simply becomes the first `ACTIVE` one and nothing else in the system changes.

**Hop 2.** Because that revision is now `SUPERSEDED`, every preparation whose `agency_form_id` points at that exact revision and whose `prep_status` is `PREPARED` or `SIGNED` moves to `STALE`. Preparations pointing at any other revision are untouched, and preparations already `STALE` or already `VOID` are untouched. When a preparation moves from `SIGNED` to `STALE` the signature dies with the revision: `signed_at` and `signed_by_user_id` are both set back to null. When it moves from `PREPARED` to `STALE` those two fields were already null and are left alone. `form_code`, `revision_used` and `filled_field_count` are never rewritten by this hop — the preparation remains an accurate record of what was filled against which revision.

**Hop 3.** Because those preparations are `STALE`, every traveller who owns one and whose `readiness_status` is `COMPLETE` regresses `COMPLETE → PENDING`. Travellers already `PENDING` are left alone, and travellers who are `WITHDRAWN` are never revived by this hop or any other.

**Hop 4.** Because those travellers regressed, every order that carries one of them and sits in `workflow_status` `READY_FOR_SUBMISSION` regresses `READY_FOR_SUBMISSION → INTAKE`, and its `feasibility_status` is reset to `UNKNOWN`. Orders in any other workflow status — `DRAFT`, `QUOTED`, `INTAKE`, `SUBMITTED`, `AT_AGENCY`, `RFE_PENDING`, `APPROVED`, `REJECTED`, `DELIVERING`, `COMPLETED`, `CANCELLED` or `ABANDONED` — are untouched by this hop. Critically, `furthest_stage_reached` is a high-water mark and is **never lowered**: an order that had reached `READY_FOR_SUBMISSION` keeps that value in `furthest_stage_reached` even as `workflow_status` falls back to `INTAKE`, and the refund schedule keyed to it therefore does not improve.

**Hop 5.** Because those orders regressed, every courier leg belonging to them whose `leg_status` is `CREATED` moves to `CANCELLED`. Legs in `DISPATCHED`, `FAILED`, `DELIVERED` or `CANCELLED` are untouched — a leg already in the courier's hands is not recalled by a paperwork change.

A traveller left holding a `STALE` preparation recovers by having a `CaseManager` prepare a fresh one against the new `ACTIVE` revision, which is covered in §3.6.

### 3.3. Missions, Closure Calendars and Bookable Interview Slots

A **consulate** is a destination country's mission. It carries a display `name`, the two-letter `destination_country` it represents, and `jurisdiction_region_codes`, a non-empty array of residence region codes it serves. Region codes are globally exclusive across consulates of the same destination country: a given region is served by exactly one mission per country. `closure_dates` starts as an empty array and holds calendar dates on which the mission is shut.

A `PlatformAdmin` adds a date to the calendar one at a time by supplying `closure_date`; the response is the updated mission. Adding a closure has an immediate side effect on capacity: every interview slot of that mission whose `starts_at` falls on the added calendar date moves to `status` `CLOSED`, whether it was `OPEN` or `FULL` at the time. Appointments already booked into a slot that closes keep `booking_status` `BOOKED` and are **not** cancelled — they must be rescheduled by hand — but no further booking or reschedule may target the closed slot. Closure also blocks courier dispatch, because a dispatch date must be a business day at the order's consulate.

Interview slots are published per mission with a `starts_at` instant and a `capacity` of at least 1. A slot tracks `booked_count`, defined as the number of appointments on it whose `booking_status` is `BOOKED` or `ATTENDED` — an attended interview continues to occupy its seat, while a no-show or a cancellation gives the seat back. `status` is derived from that count and the calendar: `OPEN` while `booked_count` is strictly less than `capacity`, `FULL` when the two are equal, and `CLOSED` when the slot's calendar date appears in the owning mission's `closure_dates`. The closure verdict dominates: a slot whose date is closed stays `CLOSED` no matter what happens to its `booked_count`, so a capacity release inside a closed date does not re-open it. A slot transitions `OPEN → FULL` the moment a booking or an inbound reschedule fills the last seat, and `FULL → OPEN` the moment a cancellation, a no-show or an outbound reschedule frees one.

### 3.4. Opening an Order and Enrolling Travellers

A `CaseManager` opens an order against a catalog item by naming `catalog_item_id`, the `travel_date` the traveller departs, the `return_date` they come back, and the `delivery_region_code` the finished passport will be shipped to. `return_date` must be on or after `travel_date`. `service_level` is optional and defaults to `STANDARD`. `consulate_id` is optional in general but is required whenever the chosen catalog item has `requires_appointment` set to true, since without a mission there is nowhere to book an interview; a request that omits it in that case is refused as a missing required field. A missing or malformed field on this payload is refused with `ERR_VALIDATION`, including a `return_date` that precedes `travel_date`.

A newly opened order starts in `workflow_status` `DRAFT`, `payment_status` `UNPAID`, `custody_holder` `APPLICANT`, `feasibility_status` `UNKNOWN` and `furthest_stage_reached` `DRAFT`, with `applicant_count`, every money roll-up field and `rfe_round_count` at 0, `discount_pct_applied` at 0, `handling_fee_waived` false, and `parent_order_id`, `quoted_by_user_id`, `submitted_by_user_id`, `acknowledged_by_user_id`, `quoted_at`, `submitted_at`, `tendered_at`, `decided_at`, `effective_submission_date` and `projected_completion_date` all null. Creation also opens the chain of custody: a first custody event is appended with `holder_type` `APPLICANT`, a null `leg_index`, `acquired_at` at the logical clock, a null `released_at` and `reason` `ORDER_CREATED`. The traveller is holding their own passport, and the system says so from the first instant.

Travellers are then enrolled one at a time with `full_name`, `date_of_birth`, `nationality_code` (again exactly two uppercase letters) and `residence_region_code`. The citizenship check is strict and is its own failure: an applicant whose `nationality_code` differs from the `nationality_code` on the order's catalog item is refused with `ERR_NATIONALITY_MISMATCH`. Enrolment does three things beyond writing the row.

First, it **pins the traveller's age**. `age_years` is the number of whole years from `date_of_birth` to the order's `travel_date` as `travel_date` stands at that instant, floored — the birthday must have fallen on or before the travel date in that year for the year to count. This value is computed **once**, at enrolment, and is deliberately **not** recomputed when the travel dates are changed later. An order whose departure is pushed a year out does not thereby make its travellers a year older in the eyes of the requirement engine.

Second, it **derives and pins the requirement set**. Starting from the requirement lines of the order's catalog item, a line applies to this traveller when its `applies_max_age_years` is null, or when the traveller's `age_years` is strictly less than that number. The applying lines form the traveller's derived set. One document slot is created for each applying line, in `review_status` `MISSING`, copying `doc_type`, `is_required`, `validity_rule` and `validity_param` from the line — optional lines produce slots too. `required_doc_count` is the number of applying lines whose `is_required` is true. Like the age, this derived set is pinned at enrolment: adding, removing or editing requirement lines on the catalog item afterwards, or changing the travel dates, or anything else that would alter the age, does **not** re-derive an existing traveller's slots.

Third, it moves the order's `applicant_count`, which counts travellers whose `readiness_status` is `PENDING` or `COMPLETE`. Withdrawn travellers are excluded from that count and from every money calculation that reads it. A new traveller starts at `readiness_status` `PENDING` with `accepted_doc_count` at 0.

A computed read exposes the derived set: it reports `required_doc_types` and `optional_doc_types` as the document classes in the required and non-required halves of the derived set, `required_doc_count` and `accepted_doc_count` as the traveller carries them, and `satisfied` as true exactly when `accepted_doc_count` equals `required_doc_count`. `accepted_doc_count` counts the traveller's document slots whose `doc_type` lies in the derived required set and whose `review_status` is `ACCEPTED`.

### 3.5. Pricing the Two Streams: Quoting, Discounts and the Handling-Fee Waiver

Quoting is a `CaseManager` capability and is the transition `DRAFT → QUOTED`; re-quoting an order already at `QUOTED` is a self-loop that is permitted without limit and overwrites every quoted money field each time. Either way the order must carry at least one traveller whose `readiness_status` is `PENDING` or `COMPLETE`; quoting an order with no such traveller is refused as an invalid state with `ERR_INVALID_STATE`. The only request field is `promo_discount_pct`, an optional decimal fraction that defaults to 0.00.

**The `GOVERNMENT` stream is priced first, and priced simply.** Let the counted traveller total be `applicant_count`, the number of travellers whose `readiness_status` is `PENDING` or `COMPLETE`; withdrawn travellers never count. When the catalog item's `government_fee_basis` is `PER_ORDER`, `government_fee_quoted_cents` is exactly the catalog item's `government_fee_cents` — a single per-file charge that does not change as travellers are added. When the basis is `PER_APPLICANT`, `government_fee_quoted_cents` is the catalog item's `government_fee_cents` multiplied by the counted traveller total, so the same catalogue number yields an n-fold larger government total. No discount, no tier surcharge, no handling fee and no waiver ever touches this figure.

**The `SERVICE` stream is priced through a seven-step waterfall whose order is pinned**, because the waiver test reads a subtotal that does not exist until after the discount has been chosen.

*Step one.* An automatic discount fraction is set to **0.10** when the counted traveller total is at least **3**, and to 0.00 otherwise.

*Step two.* `discount_pct_applied` is the smaller of two numbers: the automatic fraction plus the supplied `promo_discount_pct`, and the hard ceiling **0.25**. A promotion can therefore never take a `SERVICE` line below three quarters of its post-surcharge value, however generous the promotion.

*Step three.* The subtotal is built one line per counted traveller, and the rounding order matters. For each traveller: take the catalog item's `base_service_fee_cents`, multiply it by one plus the tier surcharge fraction for the order's `service_level` — **0.00** for `STANDARD`, **0.35** for `EXPEDITED`, **0.80** for `RUSH` — then multiply that by one minus `discount_pct_applied`, and **round that per-traveller amount half up to whole cents**. Only then are the rounded per-traveller amounts summed to give the service subtotal. Summing the unrounded amounts and rounding once at the end is explicitly **not** the specified order and will produce a different total on fractional inputs.

*Step four.* `handling_fee_waived` is true when **both** conditions hold: the counted traveller total is at least **3**, and the service subtotal from step three is at least **20000** cents. Otherwise it is false.

*Step five.* The handling component is 0 when the waiver was granted, and **3000** cents otherwise.

*Step six.* `service_fee_quoted_cents` is the service subtotal plus the handling component.

*Step seven.* `total_quoted_cents` is `government_fee_quoted_cents` plus `service_fee_quoted_cents`.

A consequence of this ordering deserves stating outright, because it is counter-intuitive and correct: **a larger discount can produce a larger total.** The waiver test in step four reads the post-discount subtotal. A promotion generous enough to drag that subtotal below 20000 cents forfeits a 3000-cent waiver, and the forfeited waiver can easily exceed the money the discount saved. The system does not protect the customer from this; it prices exactly what was asked for.

Quoting also stamps `quoted_by_user_id` with the acting `X-User-ID` and `quoted_at` with the logical clock, raises `furthest_stage_reached` to `QUOTED`, and re-runs the completion projection and its feasibility verdict described in §3.9.

**Raising the service level** is a separate `CaseManager` capability, guarded by optimistic concurrency on the order (§2.8) and by two dedicated rungs: the requested `service_level` must be strictly higher than the current one in the order `STANDARD`, `EXPEDITED`, `RUSH` — a sideways or downward request is `ERR_TIER_NOT_AN_UPGRADE` — and the order's `workflow_status` must be one of `DRAFT`, `QUOTED`, `INTAKE` or `READY_FOR_SUBMISSION`, since a tier change is closed from `SUBMITTED` onward with `ERR_UPGRADE_STAGE_CLOSED`. Which of two pricing variants runs is decided by that same `workflow_status`, and the two behave very differently.

*Before intake* — `workflow_status` `DRAFT` or `QUOTED` — the whole quote is **recomputed from scratch** at the new tier. Both streams re-run their calculations, the automatic discount and the waiver are re-evaluated against the current traveller set with the promotional component treated as 0.00, and **no administration fee is charged**. The previously quoted numbers are discarded rather than adjusted.

*In flight* — `workflow_status` `INTAKE` or `READY_FOR_SUBMISSION` — only the difference is priced. A new subtotal is computed exactly as in step three above but at the new tier's surcharge fraction, **reusing the order's recorded `discount_pct_applied` unchanged**. The old subtotal is recovered by taking the order's current `service_fee_quoted_cents` and subtracting the handling component that is currently embedded in it — 0 when `handling_fee_waived` is true, and 3000 cents when it is false. The delta is the new subtotal minus the old subtotal, **plus a 2500-cent tier-upgrade administration fee**. That delta is added to `service_fee_quoted_cents`, and `total_quoted_cents` is recomputed as `government_fee_quoted_cents` plus the new `service_fee_quoted_cents`. Both `handling_fee_waived` and `discount_pct_applied` are **frozen** at their accepted-quote values and are not re-evaluated; the `GOVERNMENT` stream is untouched entirely. Afterwards `payment_status` is re-derived and may regress, and the completion projection and feasibility verdict are re-run.

### 3.6. Collecting Money, Accepting the Quote and Balances That Re-Open

Payments are recorded by a `CaseManager` or by the `Traveler` themselves, and a payment is only meaningful against a priced order: the order's `payment_status` must be `UNPAID` or `PARTIALLY_COLLECTED` and its `total_quoted_cents` must be strictly greater than 0. The request carries `amount_cents`, a strictly positive whole number of cents, and optionally `stream_override`.

**The government bucket fills first.** Without an override, the amount is split by a two-step waterfall: the government remainder is the order's `government_fee_quoted_cents` minus its `collected_government_cents`, floored at 0; the government part of this payment is the smaller of `amount_cents` and that remainder; and the service part is whatever is left of `amount_cents`. With `stream_override` set to `GOVERNMENT` the whole amount goes to the government part and the service part is 0; with `stream_override` set to `SERVICE` the whole amount goes to the service part and the government part is 0. A `COLLECTION` ledger row with `reason` `CUSTOMER_PAYMENT` is appended for each part that is strictly positive — so an unsplit payment writes one row and a straddling payment writes two. The order's `outstanding_cents` rises by the full `amount_cents` regardless of how the split fell. The response returns the `SERVICE`-stream collection row when one was written, and the `GOVERNMENT`-stream row otherwise.

The override is the only way to break the per-stream ceiling of §2.11, and the system refuses to let it: if applying the override would leave `collected_government_cents` above `government_fee_quoted_cents`, the payment is rejected with `ERR_STREAM_ALLOCATION_INVALID` and no row is written. Without an override the waterfall makes that state unreachable by construction.

**How `payment_status` is derived.** While the order is in the collection half of the money axis — that is, while `payment_status` is `UNPAID`, `PARTIALLY_COLLECTED` or `COLLECTED` — the status is a pure function of two numbers, re-derived after every event that moves either of them: `UNPAID` while `collected_cents` is 0; `PARTIALLY_COLLECTED` while `collected_cents` is strictly between 0 and `total_quoted_cents`; and `COLLECTED` once `collected_cents` is at least `total_quoted_cents` with `total_quoted_cents` strictly above 0. This derivation runs after a payment, after a tier change, after a delivery escalation and after a split. It is what allows the money axis to **regress without the workflow moving at all**: an in-flight tier upgrade that raises `total_quoted_cents` above the money already collected pushes a settled order from `COLLECTED` straight back to `PARTIALLY_COLLECTED`, writing no ledger row and leaving `workflow_status` exactly where it was. Once the order has entered the refund half of the axis — `REFUND_PENDING`, `PARTIALLY_REFUNDED` or `REFUNDED` — those three states are set only by refund adjudication and disbursement, and the collection derivation above no longer overwrites them.

**Accepting the quote** advances `QUOTED → INTAKE` and may be performed by a `CaseManager` or by the `Traveler`. It requires the order to be fully funded: `payment_status` must be `COLLECTED` and `total_quoted_cents` must be strictly greater than 0. An acceptance attempted while money is still owed is refused as an invalid state with `ERR_INVALID_STATE`. Acceptance raises `furthest_stage_reached` to `INTAKE` and recomputes every traveller's `readiness_status`, which is how an order whose paperwork was already complete before payment can advance to `READY_FOR_SUBMISSION` on the same request.

### 3.7. Bringing a Traveller to Readiness

A traveller's `readiness_status` is the aggregate gate the order reads, and it is never set directly — it is recomputed after every event that could change it. A traveller moves `PENDING → COMPLETE` exactly when **all four** of the following hold: every one of their document slots whose `is_required` is true has `review_status` `ACCEPTED`; exactly one of their photos has `compliance_status` `PASSED`; exactly one of their preparations has `prep_status` `PREPARED` or `SIGNED` **and** a `revision_used` equal to the `revision` of the currently `ACTIVE` form carrying the product's `form_code`; and, when the order's catalog item has `requires_appointment` true, one of their appointments has `booking_status` `ATTENDED`. The moment any one of those four stops holding — a preparation goes `STALE`, an accepted document is invalidated, a passing photo expires, an interview is recorded as a no-show — the traveller regresses `COMPLETE → PENDING` and the owning order is re-evaluated for the `READY_FOR_SUBMISSION → INTAKE` regression. A traveller in `PENDING` or `COMPLETE` moves to `WITHDRAWN` when the owning order is cancelled or rejected, and `WITHDRAWN` is terminal.

**Documents.** A slot is created in `review_status` `MISSING` and receives its content when a `CaseManager` or the `Traveler` supplies `doc_type`, `issue_date` and optionally `expiry_date`; the matching slot moves `MISSING → RECEIVED` and stores both dates. Naming a `doc_type` for which the traveller holds no slot is `ERR_RESOURCE_NOT_FOUND`.

A `CaseManager` then reviews the slot with a `decision` of `ACCEPT` or `REJECT` and an optional `rejection_reason`. A reject decision moves `RECEIVED → REJECTED`, stores the supplied `rejection_reason` and stamps `reviewed_by_user_id`. An accept decision moves `RECEIVED → ACCEPTED`, clears `rejection_reason` back to null, stamps `reviewed_by_user_id`, and recomputes the traveller's `accepted_doc_count` and `readiness_status` — but only after the slot has passed its validity window, which is checked against the order's `travel_date` and `return_date` **as they stand at review time**, never against the logical clock. The validity rule chosen at configuration time decides which of three behaviours runs:

- With `validity_rule` `NONE` the slot is always valid and no date is consulted at all.
- With `validity_rule` `VALID_BEYOND_RETURN_MONTHS` the slot is valid when its `expiry_date` is on or after the order's `return_date` advanced by `validity_param` calendar months, where advancing by months clamps to the last day of a shorter target month (a 31 January anchor advanced one month lands on 28 or 29 February). When the requirement line omitted `validity_param`, the stored default of 6 months applies.
- With `validity_rule` `EXPIRES_AFTER_ISSUE_DAYS` the slot is valid when its `issue_date` advanced by `validity_param` calendar days lands on or after the order's `travel_date`. When the requirement line omitted `validity_param`, the stored default of 90 days applies.

The two windows anchor on different ends of the trip — one on the return, one on the departure — so the very same pair of document dates can pass one rule and fail the other. A slot that fails is refused with `ERR_DOCUMENT_VALIDITY_INSUFFICIENT` and stays in `RECEIVED`.

A rejected slot can be re-supplied by a `CaseManager` or the `Traveler` with a fresh `issue_date` and optional `expiry_date`. That moves `REJECTED → RECEIVED`, overwrites both dates, clears `rejection_reason` to null and increments `resubmission_count`. A slot may be re-supplied at most **twice**; a third attempt is `ERR_RESUBMISSION_CAP_EXCEEDED`.

One further path returns a slot to `RECEIVED` without consuming a resubmission. When the travel dates change, every slot in `ACCEPTED` whose `validity_rule` is anything other than `NONE` falls back `ACCEPTED → RECEIVED` and must be re-reviewed against the new dates. `resubmission_count` is explicitly **not** incremented on that path, because the traveller did nothing wrong — acceptance was pinned to the dates it was judged against. Slots whose `validity_rule` is `NONE`, and slots in `MISSING`, `RECEIVED` or `REJECTED`, are left exactly as they are.

**Photos.** A `CaseManager` or the `Traveler` uploads a photo with `taken_on`, `head_height_ratio` (strictly between 0 and 1), `background_code` and `resolution_px` (at least 1); it lands in `compliance_status` `PENDING` with an empty `failure_reasons` and `retake_count` 0. A `CaseManager` then runs the compliance check, which evaluates three named criteria in a fixed order and collects the names of the failing ones into an ordered list:

1. `HEAD_HEIGHT` fails unless `head_height_ratio` lies between **0.50** and **0.69** inclusive at both ends, compared to two decimal places.
2. `BACKGROUND` fails when `background_code` is `COLORED`. `WHITE` and `OFF_WHITE` both pass.
3. `RESOLUTION` fails when `resolution_px` is strictly below **600**. Exactly 600 passes.

The list is built in that order — head height, then background, then resolution — and written verbatim to `failure_reasons`. A non-empty list moves the photo `PENDING → FAILED` and stores the list. An empty list splits on staleness: if `taken_on` advanced by **180** calendar days is strictly before the order's `travel_date`, the photo moves `PENDING → EXPIRED` with an empty `failure_reasons`; otherwise it moves `PENDING → PASSED`, also with an empty `failure_reasons`, and the traveller's readiness is recomputed. An otherwise-flawless photo that will simply be too old on the departure date is `EXPIRED`, not `FAILED`, and the distinction matters because the two carry different meaning to the operator even though both are eligible for retake. Separately, a photo already in `PASSED` moves `PASSED → EXPIRED` when a travel-date change pushes `travel_date` beyond `taken_on` plus 180 calendar days, which regresses the traveller's readiness.

A `FAILED` or `EXPIRED` photo is superseded by a retake, performed by a `CaseManager` or the `Traveler` with a fresh `taken_on`, `head_height_ratio`, `background_code` and `resolution_px`. The source photo moves to `SUPERSEDED`, which is terminal, and a new photo is created in `PENDING` with `retake_count` one higher than the source's. A lineage supports at most **3** retakes; a fourth is `ERR_PHOTO_RETAKE_CAP_EXCEEDED`. Retakes are blocked while the passport is in agency custody.

**Prepared forms.** A `CaseManager` prepares the product's form for a traveller by naming `agency_form_id`, `filled_field_count` and `expected_applicant_version`. Two statements about `filled_field_count` stand in this document and both are carried here: its declared numeric bound is that it must be at least 0, and its definition is that it must be at least the referenced revision's `required_field_count`; a value that breaks a declared numeric bound is refused with `ERR_VALIDATION`. The named revision must currently hold `status` `ACTIVE` **and** its `form_code` must equal the `form_code` on the order's catalog item; otherwise the request is `ERR_FORM_REVISION_STALE`. The new preparation is created in `prep_status` `PREPARED`, copying `form_code` and `revision_used` from the referenced revision. Creating it is a supersede: any prior preparation of the same traveller carrying the same `form_code` moves to `VOID`, whether it stood in `PREPARED` or in `STALE`, and `VOID` is terminal. That supersession is exactly why the operation is guarded by optimistic concurrency on the traveller — a writer holding a stale view of the applicant would silently discard a preparation it had never seen — and a mismatched `expected_applicant_version` is `ERR_STALE_VERSION`.

Signing is a lighter act available to a `CaseManager` or the `Traveler`: a preparation in `PREPARED` moves `PREPARED → SIGNED`, stamping `signed_at` with the logical clock and `signed_by_user_id` with the acting `X-User-ID`, provided the revision it references is still `ACTIVE`. Signing does not change readiness, because a `PREPARED` form already satisfies the readiness condition; the signature is a record, not a gate. When a later revision supersedes the one a preparation was filled against, both `PREPARED` and `SIGNED` preparations go `STALE` and — for the signed case only — the signature is voided as described in §3.2.

**Appointments.** When the product requires an interview, a `CaseManager` books one by naming `applicant_id`, `slot_id` and `expected_slot_version`. Four checks stand between the request and a seat, and they are evaluated in ladder order. The slot's calendar date must be a business day that is not a mission closure — equivalently, the slot must not be `CLOSED` — or the booking is `ERR_EMBASSY_CLOSED`. The traveller's `residence_region_code` must appear in the target slot's mission's `jurisdiction_region_codes`, and that mission must be the order's `consulate_id`, or the booking is `ERR_OUT_OF_JURISDICTION`. The slot's `starts_at` must be at least **48 hours** after the logical clock, with exactly 48 hours passing, or the booking is `ERR_LEAD_TIME_VIOLATION`. And the slot's `booked_count` must be strictly below its `capacity`, or the booking is `ERR_SLOT_CAPACITY_EXCEEDED`. A successful booking creates the appointment in `booking_status` `BOOKED` with `reschedule_count` and `no_show_count` at 0 and `booked_at` at the logical clock, increments the slot's `booked_count` and re-derives the slot's `status`.

Rescheduling moves a booking to another slot by naming `slot_id`, and it serves two distinct situations governed by two independent counters. From `BOOKED`, the booking stays `BOOKED`, the old slot gives its seat back and re-derives its `status`, the new slot takes one and re-derives its `status`, `reschedule_count` increments and `booked_at` is restamped; a booking may be moved at most **twice** this way. From `NO_SHOW`, the booking returns `NO_SHOW → BOOKED`, only the new slot takes a seat because the old one was already released at no-show time, `booked_at` is restamped, and `reschedule_count` is **not** touched — a rebook after a missed interview consumes a no-show attempt, not a reschedule attempt, and at most **2** no-shows may be rebooked. Exceeding either counter is `ERR_RESCHEDULE_CAP_EXCEEDED`. Both flavours of reschedule re-run the closure, jurisdiction, lead-time and capacity checks against the target slot.

An `AgencyLiaison` records the interview result once the logical clock is at or after the slot's `starts_at`. An `outcome` of `ATTENDED` moves `BOOKED → ATTENDED`, which is terminal, leaves the slot's `booked_count` alone (an attended interview keeps its seat) and recomputes the traveller's readiness — potentially completing it. An `outcome` of `NO_SHOW` moves `BOOKED → NO_SHOW`, increments `no_show_count`, releases the slot's seat and re-derives the slot's `status`, and recomputes the traveller's readiness — potentially regressing it. Appointments are also cancelled without any request of their own: when a traveller is set to `WITHDRAWN`, every one of their appointments in `BOOKED` moves to `CANCELLED` and each referenced slot gives its seat back.

### 3.8. Moving the Book: Courier Legs and the Chain of Custody

The passport travels in ordered hops. A `CourierOps` operator creates a hop by supplying `leg_index` (a 1-based position of at least 1 in the order's hop sequence), `from_holder` (one of `APPLICANT`, `SERVICE`, `AGENCY`), `to_holder` (one of `SERVICE`, `AGENCY`, `APPLICANT`) and `scheduled_date`. `COURIER` is never a leg endpoint — it is the transient holder the book occupies *between* endpoints. A new hop lands in `leg_status` `CREATED` with `attempt_count` 0.

Dispatching a hop moves it `CREATED → DISPATCHED` and takes the book off the sender. Three conditions guard it, in ladder order after the generic ones: the order's `custody_holder` must equal the leg's `from_holder`, or the request is `ERR_CUSTODY_MISMATCH`; the leg must carry the **lowest** `leg_index` among the order's legs whose `leg_status` is `CREATED` or `FAILED`, or the request is `ERR_LEG_SEQUENCE_VIOLATION`; and the leg's `scheduled_date` must be a business day that does not appear in the order consulate's `closure_dates`, or the request is `ERR_EMBASSY_CLOSED`. Dispatch increments `attempt_count`, closes the open custody event by stamping its `released_at`, and appends a custody event with `holder_type` `COURIER` and `leg_index` set to this leg's index, driving the order's `custody_holder` to `COURIER`. The `reason` on that new event is `DECISION_RETURNED` when the leg's `from_holder` is `AGENCY`, and `LEG_DISPATCHED` in every other case.

Two hops carry an additional workflow condition of their own. A hop out of `SERVICE` towards the agency is declared only while the order's `workflow_status` is `SUBMITTED`. A hop out of `AGENCY` — the return leg — is declared while the order's `workflow_status` is `APPROVED`, `REJECTED`, `CANCELLED` or `ABANDONED`. Note the tension the second of these creates with rung 9: rung 9 refuses every mutating endpoint that touches an order whose `workflow_status` is `COMPLETED`, `CANCELLED` or `ABANDONED`, and courier dispatch and completion sit on the rung-8 exclusion list but carry no rung-9 exemption, while the custody axis explicitly declares the return hop out of `AGENCY` from `CANCELLED` and from `ABANDONED`. Both statements are requirements of this document.

Completing a hop takes an `outcome` of `DELIVERED` or `FAILED` and is only available from `leg_status` `DISPATCHED`. On `DELIVERED` the hop moves `DISPATCHED → DELIVERED`, the open custody event is closed and a new one is appended with `holder_type` equal to the leg's `to_holder` and `reason` `LEG_DELIVERED`, driving the order's `custody_holder` to that holder. Arriving at `AGENCY` is the moment the agency-custody write gate of §2.7 becomes active for the order; leaving `AGENCY` on the return dispatch is the moment it becomes inactive again. Arriving at `SERVICE` re-evaluates every traveller's readiness and the order's `INTAKE → READY_FOR_SUBMISSION` gate, and — when the order's `payment_status` is `REFUND_PENDING` — disburses the scheduled refund as described in §3.11. On `FAILED` the hop moves `DISPATCHED → FAILED`, the open custody event is closed and a new one is appended with `holder_type` equal to the leg's `from_holder` and `reason` `LEG_FAILED_RETURN`: the book goes back to whoever sent it.

A failed hop may be re-dispatched, moving `FAILED → DISPATCHED` and incrementing `attempt_count` again, subject to the same custody, sequence and calendar checks. A leg supports at most **2** re-dispatches after its first attempt, so `attempt_count` may reach 3 but a fourth dispatch is `ERR_COURIER_ATTEMPT_CAP_EXCEEDED`.

Hops also die without a request of their own. When an order regresses `READY_FOR_SUBMISSION → INTAKE`, every one of its hops in `leg_status` `CREATED` moves to `CANCELLED`. When an order is cancelled, hops move to `CANCELLED` as well; the hop axis declares cancellation from `CREATED` and from `FAILED`, and the cancellation operation is described as cancelling every hop in `CREATED` or `FAILED`, while two of the workflow cancellation transitions describe it as cancelling every hop in `CREATED` or `DISPATCHED`. Both descriptions are carried by this document. `DELIVERED` and `CANCELLED` are terminal for a hop.

### 3.9. Projection, Feasibility, Travel-Date Changes and Submission

Every quote, every readiness completion, every tier change and every travel-date change asks the same question: will the passport be back in time?

**The effective submission date.** The agency treats a file as submitted on a date that depends on the hour of day and the service level, because each tier has its own daily cutoff: hour **21** UTC for `STANDARD`, hour **18** UTC for `EXPEDITED` and hour **15** UTC for `RUSH`. When the calendar date of the logical clock is a business day at the order's consulate **and** the hour of the logical clock is strictly below that tier's cutoff hour, the effective submission date is that same calendar date. Otherwise it is that date advanced by one business day. The comparison against the cutoff is strict: submitting exactly *at* the cutoff hour rolls the file to the next business day.

**The agency turnaround.** How long the agency takes is either a per-product override or a per-tier default. When the order's catalog item carries a non-null `agency_turnaround_override_days`, that number of business days replaces the tier constant entirely — and the consequence is worth naming, because it is the trap in this calculation: upgrading the tier on such a product buys **no** turnaround improvement whatsoever, only a surcharge and a tighter cutoff. When the override is null, the tier default applies: **15** business days for `STANDARD`, **8** for `EXPEDITED`, **3** for `RUSH`.

**The completion projection.** Two variants exist and the selector is whether the order has been submitted yet.

*Before submission* — `submitted_at` is null, and the read reports `variant_used` as `tier_nominal`. Start from the effective submission date computed as if the order were submitted at the current logical clock. Advance that by **1** business day for the outbound courier hop from the expediter to the agency. Advance the result by the agency turnaround in business days. Advance that by **1** business day for the return courier hop from the agency back to the expediter. Advance that by **2** business days for the final delivery. The date reached is `projected_completion_date`. Every one of those four advances uses the order consulate's closure calendar when `consulate_id` is set, and the plain weekday test when it is not.

*After submission* — `submitted_at` is not null, and the read reports `variant_used` as `observed_actual`. The outbound hop is already spent and the agency has already consumed part of its window, so the projection restarts from today and credits elapsed running clock. Take the calendar date of the logical clock, advanced forward to the next business day when today is not one. Divide the order's clock-stop SLA figure in business minutes by **480** minutes per business day and take the floor; that is the number of turnaround days already consumed. The remaining turnaround is the agency turnaround minus the consumed days, floored at 0. Advance the base date by that remaining number of business days, then by **1** business day for the return courier hop, then by **2** business days for delivery. The date reached is `projected_completion_date`.

**The feasibility verdict.** Immediately after every projection, the deadline date is computed as the order's `travel_date` minus **5** calendar days — a wall-calendar cushion, not a business-day one. `feasibility_status` is `FEASIBLE` when `projected_completion_date` is on or before that deadline date, and `INFEASIBLE` when it is strictly after. The boundary is inclusive: landing exactly on the deadline date is `FEASIBLE`. Whenever this evaluation re-runs it revokes any standing acknowledgment — an order sitting at `ACKNOWLEDGED_INFEASIBLE` is written back down to `INFEASIBLE` or up to `FEASIBLE` — and `acknowledged_by_user_id` is set back to null on every verdict other than `ACKNOWLEDGED_INFEASIBLE` itself.

A `ComplianceOfficer` may override an infeasible projection. The acknowledgment requires `feasibility_status` to be exactly `INFEASIBLE` and `workflow_status` to be `INTAKE` or `READY_FOR_SUBMISSION`; it moves `INFEASIBLE → ACKNOWLEDGED_INFEASIBLE` and stamps `acknowledged_by_user_id` with the acting `X-User-ID`. Because the acknowledgment is pinned to the projection it was granted against, changing the travel dates afterwards revokes it and drops the order back to `INFEASIBLE`, and a subsequent tier upgrade that repairs the projection lifts it to `FEASIBLE` — in both directions `acknowledged_by_user_id` returns to null.

**The feasibility read** exposes the whole computation for auditing: it reports `effective_submission_date`, `agency_turnaround_days`, `projected_completion_date`, `deadline_date`, `feasibility_status` and `variant_used`. It is a pure read and writes nothing — it does not persist a recomputed projection onto the order, does not move the stored `feasibility_status`, and does not revoke an acknowledgment; the `feasibility_status` it returns is the order's stored value. Note that the stored `effective_submission_date` on the order itself is written only at submission and stays null until then, while the read reports the value its own projection used.

**Changing the travel dates** is available to a `CaseManager` or the `Traveler` and takes both `travel_date` and `return_date`, with `return_date` on or after `travel_date`. It is one of the most destructive routine operations in the system, and the legs that do **not** fire matter as much as those that do. Every document slot in `ACCEPTED` whose `validity_rule` is anything other than `NONE` falls back to `RECEIVED` and must be re-reviewed — with `resubmission_count` untouched, `issue_date` and `expiry_date` untouched, and `reviewed_by_user_id` and `rejection_reason` left as they stand. Slots whose `validity_rule` is `NONE` keep their acceptance; slots in `MISSING`, `RECEIVED` or `REJECTED` are not moved. Every photo in `PASSED` whose `taken_on` plus 180 calendar days now falls strictly before the new `travel_date` moves to `EXPIRED`; photos still inside their window keep `PASSED`, and photos in `PENDING`, `FAILED`, `EXPIRED` or `SUPERSEDED` are untouched. Travellers' readiness is recomputed and the order's readiness gate re-evaluated, which may regress the order `READY_FOR_SUBMISSION → INTAKE` and cancel its `CREATED` hops. The projection and feasibility verdict are re-run and any acknowledgment revoked. Two things are pointedly **not** recomputed: no traveller's `age_years` is recalculated, and no traveller's derived requirement set is re-derived — both were pinned at enrolment and stay pinned.

**Advancing to readiness and back.** The order's move `INTAKE → READY_FOR_SUBMISSION` is a system transition, not a request: it fires the moment the last qualifying readiness mutation lands — a document review, a photo check, a form preparation or signature, an appointment outcome, or a courier hop completing — and it requires that every traveller of the order whose `readiness_status` is `PENDING` or `COMPLETE` is `COMPLETE`, and that the order's `custody_holder` is `SERVICE`. It raises `furthest_stage_reached` to `READY_FOR_SUBMISSION` and re-runs the projection and feasibility verdict. The reverse move `READY_FOR_SUBMISSION → INTAKE` fires the moment any traveller regresses to `PENDING` or the `custody_holder` leaves `SERVICE`; it does **not** lower `furthest_stage_reached`, it cancels every hop in `CREATED`, and it resets `feasibility_status` to `UNKNOWN`.

**Submission** is a `CaseManager` capability and drives `READY_FOR_SUBMISSION → SUBMITTED`. Five ladder rungs guard it and their relative order is the contract: first the duty separation at rung 12 — the acting `X-User-ID` must differ from the order's `quoted_by_user_id`, or the request is `ERR_SEGREGATION_OF_DUTIES`, so the operator who priced the file may never be the operator who commits it; then completeness at rung 34 — every traveller whose `readiness_status` is `PENDING` or `COMPLETE` must be `COMPLETE`, or the request is `ERR_REQUIRED_DOCUMENTS_INCOMPLETE`; then the rush cutoff at rung 35 — when `service_level` is `RUSH`, the logical clock hour must be strictly below 15 and the current date must be a business day, or the request is `ERR_RUSH_CUTOFF_MISSED`; then feasibility at rung 36 — `feasibility_status` must be `FEASIBLE` or `ACKNOWLEDGED_INFEASIBLE`, or the request is `ERR_TRAVEL_DATE_INFEASIBLE`; and finally funding at rung 37 — `outstanding_cents` must be at least `total_quoted_cents`, or the request is `ERR_BALANCE_OUTSTANDING` with HTTP 402. Because rung 12 sits above all of them, an order that is simultaneously unfunded and self-submitted reports the duty violation, not the balance. The submission transition also requires the order's `custody_holder` to be `SERVICE`; rung 14's custody scopes are dispatch, shipment creation, first delivery attempt and tender, and do not name submission, so an order whose custody has left `SERVICE` will in practice have regressed to `INTAKE` with `feasibility_status` reset to `UNKNOWN` and be stopped at rung 36.

A successful submission stamps `submitted_at` with the logical clock and `submitted_by_user_id` with the acting `X-User-ID`, computes and writes `effective_submission_date`, raises `furthest_stage_reached` to `SUBMITTED`, appends a `SERVICE`-stream `EARN` ledger row for exactly `service_fee_quoted_cents` with `reason` `SERVICE_RECOGNITION` — reducing `outstanding_cents` by that same amount and raising `service_earned_cents` by it — and opens the SLA clock by appending the first SLA segment with `segment_kind` `RUNNING`, `cause` `SUBMISSION`, `started_at` at the logical clock, a null `ended_at` and a null `business_minutes`.

### 3.10. At the Agency: Tender, Evidence Requests and the Partitioned SLA Clock

Once the outbound hop has delivered the book into `AGENCY` custody, an `AgencyLiaison` acknowledges receipt, driving the order `SUBMITTED → AT_AGENCY`. Two conditions guard it: the order's `custody_holder` must be `AGENCY`, or the request is `ERR_CUSTODY_MISMATCH`, and `tendered_at` must still be null. Tender stamps `tendered_at` with the logical clock, raises `furthest_stage_reached` to `AT_AGENCY`, and appends a `GOVERNMENT`-stream `TENDER` ledger row for exactly `government_fee_quoted_cents` with `reason` `AGENCY_TENDER` — reducing `outstanding_cents` by that amount and raising `government_tendered_cents` by it. From this instant the pass-through money belongs to the agency and no refund path can ever bring it back.

**Evidence requests pause the clock.** An `AgencyLiaison` issues one by supplying `requested_doc_type`, driving the order `AT_AGENCY → RFE_PENDING`, provided the order's `rfe_round_count` is below **2** — a third request is `ERR_RFE_ROUND_CAP_EXCEEDED`. `rfe_round_count` counts every evidence-request row under the order whatever its `rfe_status`, so a cleared or expired round still consumes one of the two. The new record starts in `rfe_status` `OPEN` with `round_index` one higher than the order's current `rfe_round_count`, `issued_at` at the logical clock, `responded_at` null and `response_count` 0. Its `deadline_at` is computed by advancing the calendar date of `issued_at` by **10** business days on the order consulate's calendar and taking that date at 17:00:00Z — the deadline instant always lands at the close of the business window. Issuing also closes the open `RUNNING` SLA segment by stamping its `ended_at` with the logical clock and computing its `business_minutes`, then appends a new segment with `segment_kind` `PAUSED`, `cause` `RFE_ISSUED`, `started_at` at the same instant, a null `ended_at` and a null `business_minutes`.

A `CaseManager` or the `Traveler` responds, moving the record `OPEN → RESPONDED`, stamping `responded_at` with the logical clock and incrementing `response_count`. The response must arrive at or before `deadline_at`, and exact equality passes; a later response is `ERR_RFE_DEADLINE_PASSED`. Responding changes nothing on the order and does not touch the SLA clock — the segments stay exactly as the issuance left them, with the clock still `PAUSED`.

An `AgencyLiaison` then adjudicates with an `outcome` of `CLEARED`, `INSUFFICIENT` or `EXPIRED`, and the three branches diverge sharply.

*`CLEARED`* is available from `rfe_status` `RESPONDED`. The record moves `RESPONDED → CLEARED`, the order returns `RFE_PENDING → AT_AGENCY`, the open `PAUSED` segment is closed with its `ended_at` and `business_minutes` written, and a fresh segment with `segment_kind` `RUNNING` and `cause` `RFE_RESPONDED` is opened. The clock resumes.

*`INSUFFICIENT` below the cap* — available from `RESPONDED` while `response_count` is below **2** — re-opens the same record rather than escalating: it moves `RESPONDED → OPEN`, restamps `issued_at` with the logical clock and recomputes `deadline_at` from that new instant. The order stays in `RFE_PENDING`, the clock stays `PAUSED`, and **no SLA segment is written or closed** — the existing paused segment simply keeps running.

*`INSUFFICIENT` at the cap* — from `RESPONDED` with `response_count` at 2 or above — moves the record `RESPONDED → INSUFFICIENT` and abandons the order. *`EXPIRED`* is available from `rfe_status` `OPEN` and requires the logical clock to be strictly after `deadline_at`; it moves the record `OPEN → EXPIRED` and likewise abandons the order. Both abandoning branches do the same four things: the order moves `RFE_PENDING → ABANDONED`, the open `PAUSED` segment is closed with its `ended_at` and `business_minutes` written, `decided_at` is stamped with the logical clock, the post-tender refund adjudication of §3.11 runs and sets `refund_scheduled_cents` with `payment_status` moving to `REFUND_PENDING`, and a return hop from `AGENCY` to `SERVICE` is created in `leg_status` `CREATED` with a `leg_index` one above the highest existing hop on the order and a `scheduled_date` equal to the calendar date of the logical clock.

**Reading the clock.** Two SLA figures are reported side by side, and they measure different things. The **clock-stop** figure — the contractual one — is the sum of `business_minutes` over the order's segments with `segment_kind` `RUNNING`, plus, when the single open segment is itself `RUNNING`, the business minutes between that segment's `started_at` and the end instant. `PAUSED` segments contribute exactly zero to it: an open evidence request stops the clock. The **gross** figure ignores segment kinds entirely and is simply the business minutes between the order's `submitted_at` and the end instant, computed in one shot. In both cases the end instant is the order's `decided_at` when a decision has been recorded, and the logical clock now when one has not. Whenever any paused segment carries positive business minutes the gross figure is strictly larger than the clock-stop figure, and the difference is exactly the paused total.

The order summary reports all three: `sla_running_business_minutes` is the clock-stop figure; `sla_gross_business_minutes` is the gross figure; and `sla_paused_business_minutes` is the sum of `business_minutes` over closed `PAUSED` segments plus, when the single open segment is `PAUSED`, the business minutes between its `started_at` and the end instant. The three satisfy the partition of §2.11 at every instant: running plus paused equals gross.

### 3.11. The Decision, Refund Adjudication and Return Delivery

An `AgencyLiaison` returns the verdict with a `decision` of `APPROVED` or `REJECTED`, available while the order is at `AT_AGENCY` and no evidence request of the order stands in `rfe_status` `OPEN` or `RESPONDED`. Both branches stamp `decided_at` with the logical clock, close the open SLA segment by writing its `ended_at` and `business_minutes`, and create the return hop from `AGENCY` to `SERVICE` in `leg_status` `CREATED`, with a `leg_index` one above the highest existing hop on the order and a `scheduled_date` equal to the calendar date of the logical clock at decision time.

**The approval branch** moves the order `AT_AGENCY → APPROVED` and additionally appends one more SLA segment — `segment_kind` `RUNNING`, `cause` `DECISION`, with `started_at` and `ended_at` both equal to the decision instant and `business_minutes` exactly 0 — a zero-length terminator that closes the partition at `decided_at`. No traveller, appointment or slot is touched.

**The rejection branch** moves the order `AT_AGENCY → REJECTED`, appends **no** further SLA segment (the closed segment's `ended_at` already equals `decided_at`), runs the post-tender refund adjudication below, and then walks a four-level transitive cascade in which each hop is caused by the one before it. *Hop 1:* every traveller of this order whose `readiness_status` is `PENDING` or `COMPLETE` is set to `WITHDRAWN`; travellers already `WITHDRAWN` are untouched. *Hop 2:* because those travellers are now withdrawn, every appointment of theirs whose `booking_status` is `BOOKED` moves to `CANCELLED`; appointments in `ATTENDED`, `NO_SHOW` or `CANCELLED` are untouched. *Hop 3:* because those appointments were cancelled, each referenced slot's `booked_count` is decremented and its `status` re-derived — a slot that was `FULL` returns to `OPEN` once `booked_count` falls below `capacity`, while a slot whose calendar date sits in its mission's `closure_dates` stays `CLOSED` regardless. Slots referenced only by appointments that were not cancelled do not move at all.

**Refund adjudication** runs from three places — a cancellation, an agency rejection, and an evidence-request abandonment at the cap or past the deadline — and always begins the same way. The stage fraction is read from `furthest_stage_reached`, the high-water mark that never falls: **1.00** at `DRAFT`, **1.00** at `QUOTED`, **0.75** at `INTAKE`, **0.50** at `READY_FOR_SUBMISSION`, **0.25** at `SUBMITTED` and **0.15** at `AT_AGENCY`. The service refund is the order's `collected_service_cents` multiplied by that fraction, rounded half up to whole cents. Only this order's own collections participate — a split child's collections are never refunded by the parent, and vice versa.

What happens to the government half, and when the money actually moves, is decided by one selector: whether `government_tendered_cents` is 0.

*The pre-tender variant* runs when `government_tendered_cents` is 0. The government refund is the whole of `collected_government_cents` — the pass-through money never reached the agency, so all of it comes back. `REFUND` ledger rows with `reason` `CANCELLATION_REFUND` are written **immediately**, one per stream, and only for a stream whose refund amount is strictly positive. `payment_status` moves straight to `PARTIALLY_REFUNDED` when the total refund is strictly between 0 and `collected_cents`, and straight to `REFUNDED` when the total refund equals `collected_cents`.

*The post-tender variant* runs when `government_tendered_cents` is strictly above 0. The government refund is **0** — the pass-through money is with the agency and is never returned. No ledger row is written yet: instead `refund_scheduled_cents` is set to the adjudicated total and `payment_status` moves to `REFUND_PENDING`. The rows are appended only when the return hop from `AGENCY` to `SERVICE` reaches `leg_status` `DELIVERED`; at that moment a `REFUND` row with `reason` `REJECTION_REFUND` is written for the scheduled amount, `refund_scheduled_cents` is reset to 0, and `payment_status` moves `REFUND_PENDING → PARTIALLY_REFUNDED`. A post-tender refund is always strictly smaller than `collected_cents`, because the tendered government fee never comes back and the deepest service fraction is 0.15, so this path can never reach `REFUNDED`; the fully-refunded terminal is reachable only through the pre-tender path.

Whenever a refund is actually disbursed the pinned draw of §2.11 governs how it is funded: take the smaller of the refund and `outstanding_cents` out of `outstanding_cents`, take whatever remains out of `service_earned_cents`, and add the full refund to `refunded_cents`.

**Return delivery.** With the book back at `SERVICE`, a `CourierOps` operator creates the shipment, driving the order `APPROVED → DELIVERING` or `REJECTED → DELIVERING`. The order's `custody_holder` must be `SERVICE`, or the request is `ERR_CUSTODY_MISMATCH`. The request carries `method` (`GROUND`, `OVERNIGHT` or `COURIER_SAME_DAY`), `address_region_code`, and an optional `signature_required` that defaults to true. The shipment lands in `delivery_status` `CREATED` with `attempt_count` 0.

Creation runs an escalation test. Count the whole calendar days from the calendar date of the logical clock to the order's `travel_date`. When the requested `method` is `GROUND` **and** that count is at most **7** days — the comparison is inclusive, so exactly 7 escalates — the shipment's `method` is forced to `OVERNIGHT`, its `escalation_fee_cents` is set to **4500**, the order's `service_fee_quoted_cents` rises by 4500, `total_quoted_cents` is recomputed as `government_fee_quoted_cents` plus the new `service_fee_quoted_cents`, and `payment_status` is re-derived against the new total. In every other case — a request for `OVERNIGHT`, a request for `COURIER_SAME_DAY`, or a `GROUND` request with more than 7 days of runway — the requested method is honoured and `escalation_fee_cents` is 0. **No ledger row is written by the escalation**: the surcharge is a new charge on the `SERVICE` stream, not a recognition of money already collected, so the money conservation identity is untouched and only the quoted total moves.

A `CourierOps` operator then records attempts with an `outcome` of `DELIVERED` or `FAILED` and an optional `signature_captured`. From `CREATED` the order's `custody_holder` must be `SERVICE`. A `FAILED` first attempt moves the shipment `CREATED → OUT_FOR_DELIVERY`, sets `attempt_count` to 1, and hands the book to the carrier: the open custody event is closed and a new one is appended with `holder_type` `COURIER`, a null `leg_index` and `reason` `LEG_DISPATCHED`. A `DELIVERED` attempt requires either that the shipment's `signature_required` is false, or that the request carries `signature_captured` set to true — a `DELIVERED` attempt on a signature-required shipment without `signature_captured` is refused with `ERR_VALIDATION`. A successful first attempt moves the shipment `CREATED → DELIVERED`, sets `attempt_count` to 1, closes the open custody event and appends one with `holder_type` `APPLICANT`, a null `leg_index` and `reason` `SHIPMENT_DELIVERED`, and completes the order. Note the tension here: the custody axis declares a hop from `COURIER` to `APPLICANT`, conditioned on the order's `custody_holder` being `COURIER` with a null `leg_index` on the open event, and declares no direct hop from `SERVICE` to `APPLICANT`; the first-attempt success path nonetheless moves the book from `SERVICE` straight into `APPLICANT` custody in a single request. Both statements are carried by this document.

From `OUT_FOR_DELIVERY` the arithmetic of the cap governs. A `FAILED` attempt increments `attempt_count`; while the incremented value is strictly below **3** the shipment stays `OUT_FOR_DELIVERY`, and when the incremented value reaches exactly 3 the shipment moves `OUT_FOR_DELIVERY → HELD_FOR_PICKUP` and accepts no further delivery attempts. A `DELIVERED` attempt from `OUT_FOR_DELIVERY`, subject to the same signature condition, increments `attempt_count`, moves the shipment to `DELIVERED`, closes the open custody event and appends one with `holder_type` `APPLICANT` and `reason` `SHIPMENT_DELIVERED`, and completes the order. Any attempt against a shipment that already sits at `HELD_FOR_PICKUP`, or whose `attempt_count` has already reached 3, is `ERR_DELIVERY_ATTEMPT_CAP_EXCEEDED`.

A held shipment is closed out by recording a pickup, which moves it `HELD_FOR_PICKUP → PICKED_UP`, closes the open custody event and appends one with `holder_type` `APPLICANT` and `reason` `SHIPMENT_PICKED_UP`, and completes the order. `DELIVERED` and `PICKED_UP` are both terminal for a shipment.

**Completion.** The order moves `DELIVERING → COMPLETED` the moment its shipment reaches `DELIVERED` or `PICKED_UP`, which requires the order's `custody_holder` to be `APPLICANT` at that point. Completion has one money effect and it is conditional: `payment_status` is set to `REFUNDED` when `refunded_cents` equals `collected_cents`, and is otherwise left exactly as it stands.

Finally, the delivery region may be corrected at any time by a `CaseManager` or the `Traveler`, who supplies a new `address_region_code`. This is one of the few order-touching mutations explicitly permitted while the passport sits in agency custody, because the address is administrative and the book is untouched by it. It changes nothing else: no state moves, no money moves, and the order itself is not modified.

### 3.12. Splitting, Cancelling and Abandoning an Order

**Splitting** lets a `CaseManager` peel ready travellers off into their own order so that the rest of the file is not held hostage. It is available while the parent is at `INTAKE` or at `READY_FOR_SUBMISSION`, and the parent's `workflow_status` does not change: an `INTAKE` parent stays at `INTAKE` and a `READY_FOR_SUBMISSION` parent stays at `READY_FOR_SUBMISSION`, the latter because every traveller left behind is by definition still `COMPLETE`. The request names `applicant_ids` and may carry `transfer_cents_override`. Every named traveller must belong to this order and carry `readiness_status` `COMPLETE`, and at least one traveller must remain on the parent, or the request is `ERR_APPLICANT_NOT_READY`.

A child order is created carrying `parent_order_id` pointing at the parent and copying the parent's `catalog_item_id`, `consulate_id`, `service_level`, `travel_date`, `return_date` and `delivery_region_code`. It starts in `workflow_status` `INTAKE` with `furthest_stage_reached` `INTAKE`, its `custody_holder` initialised to the parent's current holder, and its own first custody event appended with that `holder_type` and `reason` `ORDER_CREATED`. Every named traveller is re-parented to the child, and their document slots, photos, preparations and appointments follow them automatically because those records key off the traveller rather than the order. The response is the newly created child order.

The money is then partitioned. Let the moved count be the number of entries in `applicant_ids` and the parent's pre-move count be its `applicant_count` measured **before** any traveller is re-parented. The government transfer is the parent's `collected_government_cents` multiplied by the moved count and divided by the pre-move count, rounded half up to whole cents; the service transfer is the parent's `collected_service_cents` treated the same way. The two streams are rounded **independently** and are never netted against each other. Their sum is the transfer total, and when `transfer_cents_override` is supplied it must equal exactly that sum or the request is `ERR_SPLIT_PARTITION_MISMATCH`. On the parent, a `TRANSFER_OUT` row is written for each stream whose transfer is strictly positive; on the child, mirror `TRANSFER_IN` rows with identical streams and identical amounts. Every one of these rows carries `reason` `SPLIT_PARTITION`.

The parent is additionally charged a split administration fee as a `SERVICE`-stream `EARN` row with `reason` `SPLIT_PARTITION`, which moves money out of `outstanding_cents` into `service_earned_cents` without changing `collected_cents`. Two descriptions of that charge stand in this document: the split money partition specifies the charge as the smaller of **1500** cents and the parent's `outstanding_cents` measured after the transfer, while the split operation's own description specifies the charge as 1500 cents. Both are requirements here.

Finally **both** orders re-run their government and service pricing against their own traveller sets, with the promotional discount component treated as 0.00 — a promotion never survives a split — overwriting `government_fee_quoted_cents`, `service_fee_quoted_cents`, `total_quoted_cents`, `discount_pct_applied` and `handling_fee_waived` on each. `applicant_count`, the collected roll-ups, `outstanding_cents` and `payment_status` are recomputed on both, and the readiness gate is re-evaluated on both. Neither order's `furthest_stage_reached` moves.

**Cancelling** is available to a `CaseManager` or the `Traveler` from `workflow_status` `DRAFT`, `QUOTED`, `INTAKE`, `READY_FOR_SUBMISSION`, `SUBMITTED` and `AT_AGENCY`; the workflow transitions out of `SUBMITTED` and out of `AT_AGENCY` name the `CaseManager` as their actor, while the cancellation operation's authorized-role list admits both roles at every stage. Cancellation from the first five of those states requires the order's `custody_holder` not to be `AGENCY`, and runs the pre-tender refund variant when nothing has been tendered. Cancellation from `AT_AGENCY` is the cancellation-with-restrictions path: it is on the agency-custody gate's exclusion list precisely so that it can be reached, and it demands the request carry `acknowledge_government_fee_forfeit` set to true, or it is refused with `ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED` — the tendered government fee is gone and the customer must say so in writing.

The consequences stack by stage. Every cancellation runs refund adjudication in the variant selected by `government_tendered_cents`, and sets every traveller of the order to `readiness_status` `WITHDRAWN`, which in turn moves each of their `BOOKED` appointments to `CANCELLED` and releases the corresponding slot capacity — the `AT_AGENCY` cancellation transition itself lists only the money, SLA and hop effects, and the operation's own description applies the traveller withdrawal to every cancellation; both are carried here. Cancelling from `INTAKE` or `READY_FOR_SUBMISSION` additionally cancels the order's outstanding courier hops. Cancelling from `SUBMITTED` or from `AT_AGENCY` additionally closes the open SLA segment by writing its `ended_at` and `business_minutes`. Cancelling from `AT_AGENCY` additionally sets `refund_scheduled_cents` with `payment_status` moving to `REFUND_PENDING`, and creates the return hop from `AGENCY` to `SERVICE` in `leg_status` `CREATED` with a `leg_index` one above the highest existing hop and a `scheduled_date` equal to the calendar date of the logical clock.

**Abandonment** is not a request at all. `ABANDONED` is reached only from `RFE_PENDING`, when an evidence request is adjudicated `INSUFFICIENT` at the round cap or `EXPIRED` past its deadline, as described in §3.10. Like `COMPLETED` and `CANCELLED`, it is terminal: every mutating endpoint that touches the order afterwards is refused with `ERR_ORDER_TERMINAL`.

---

## 4. Endpoint Definitions

Every endpoint below is mounted under the `/expediting` prefix. Creation endpoints that mint a brand-new resource answer **201 Created**; every other successful call answers **200 OK**. The table gives only the HTTP contract and the authorized roles — the request payloads, response bodies, side effects, state transitions and error conditions are specified in §2 and §3 and must be read from there.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/expediting/catalog-items` | Create a product row for a (nationality, destination, visa type) triple. | `PlatformAdmin` |
| GET | `/expediting/catalog-items` | List catalog items with optional filters. | `PlatformAdmin`, `CaseManager` |
| GET | `/expediting/catalog-items/{id}` | Read one catalog item. | `PlatformAdmin`, `CaseManager` |
| POST | `/expediting/catalog-items/{id}/document-requirements` | Add a required-or-optional document line to a product. | `PlatformAdmin` |
| GET | `/expediting/catalog-items/{id}/document-requirements` | List the requirement lines of a product. | `PlatformAdmin`, `CaseManager` |
| POST | `/expediting/agency-forms` | Register a new revision of a government form in DRAFT. | `PlatformAdmin` |
| GET | `/expediting/agency-forms` | List form revisions. | `PlatformAdmin`, `CaseManager` |
| GET | `/expediting/agency-forms/{id}` | Read one form revision. | `PlatformAdmin`, `CaseManager` |
| POST | `/expediting/agency-forms/{id}/publish` | Publish a DRAFT revision. Root of the depth-5 staleness cascade. | `PlatformAdmin` |
| GET | `/expediting/agency-forms/{id}/prepared-forms` | List every preparation filled against this exact form revision. | `PlatformAdmin`, `CaseManager` |
| POST | `/expediting/consulates` | Create a mission with an exclusive residence-region jurisdiction. | `PlatformAdmin` |
| GET | `/expediting/consulates` | List missions. | `PlatformAdmin`, `CaseManager` |
| GET | `/expediting/consulates/{id}` | Read one mission including its closure calendar. | `PlatformAdmin`, `CaseManager` |
| POST | `/expediting/consulates/{id}/closures` | Add a calendar date to the mission's closure list. | `PlatformAdmin` |
| POST | `/expediting/consulates/{id}/slots` | Publish a bookable interview slot. | `PlatformAdmin` |
| GET | `/expediting/consulates/{id}/slots` | List a mission's slots. | `PlatformAdmin`, `CaseManager` |
| GET | `/expediting/slots/{id}` | Read one slot including booked_count and version. | `PlatformAdmin`, `CaseManager` |
| POST | `/expediting/orders` | Open an order against a catalog item. | `CaseManager` |
| GET | `/expediting/orders` | List orders with filters; also the reverse-reachability read for catalog_item_id, consulate_id and parent_order_id. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| GET | `/expediting/orders/{id}` | Read one order including all four state axes and the money roll-up. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/orders/{id}/applicants` | Add a traveller to the order and materialise their document slots. | `CaseManager` |
| GET | `/expediting/orders/{id}/applicants` | List the travellers on an order. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| GET | `/expediting/applicants/{id}` | Read one traveller including readiness_status, age_years and version. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/orders/{id}/quote` | Price the order across both money streams. | `CaseManager` |
| POST | `/expediting/orders/{id}/accept-quote` | Accept the quote and move the order into intake. | `CaseManager`, `Traveler` |
| POST | `/expediting/orders/{id}/payments` | Record a customer payment; the government bucket fills first unless stream_override says otherwise. | `CaseManager`, `Traveler` |
| GET | `/expediting/orders/{id}/ledger-entries` | List the order's money rows. | `PlatformAdmin`, `CaseManager`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/orders/{id}/service-level` | Raise the service level. Prices as a full re-quote before intake and as a delta once in flight. | `CaseManager` |
| PATCH | `/expediting/orders/{id}/travel-dates` | Change the travel and return dates; invalidates date-anchored acceptances. | `CaseManager`, `Traveler` |
| GET | `/expediting/orders/{id}/feasibility` | Computed read of the completion projection and its verdict. | `PlatformAdmin`, `CaseManager`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/orders/{id}/feasibility-acknowledgment` | Privileged acknowledgment that lets an INFEASIBLE order proceed. | `ComplianceOfficer` |
| POST | `/expediting/orders/{id}/submit` | Submit the order to the agency pipeline. | `CaseManager` |
| POST | `/expediting/orders/{id}/split` | Move ready applicants into a new child order and partition the money. | `CaseManager` |
| POST | `/expediting/orders/{id}/cancel` | Cancel the order. Permitted while the passport is in agency custody only with an explicit forfeit acknowledgment. | `CaseManager`, `Traveler` |
| GET | `/expediting/orders/{id}/summary` | Computed read of the money conservation identity, the custody cardinality and both SLA variants. | `PlatformAdmin`, `CaseManager`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/orders/{id}/tender` | Agency acknowledges receipt; the pass-through fee is handed over. | `AgencyLiaison` |
| POST | `/expediting/applicants/{id}/documents` | Submit a document into its MISSING slot. | `CaseManager`, `Traveler` |
| GET | `/expediting/applicants/{id}/documents` | List a traveller's document slots. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| GET | `/expediting/documents/{id}` | Read one document slot. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/documents/{id}/review` | Accept or reject a received document. | `CaseManager` |
| POST | `/expediting/documents/{id}/resubmit` | Re-supply a rejected document. | `CaseManager`, `Traveler` |
| GET | `/expediting/applicants/{id}/required-documents` | Computed read of the derived requirement set and how much of it is satisfied. | `PlatformAdmin`, `CaseManager`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/applicants/{id}/photos` | Upload a passport photo for compliance checking. | `CaseManager`, `Traveler` |
| GET | `/expediting/applicants/{id}/photos` | List a traveller's photo submissions. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/photos/{id}/compliance-check` | Run the three named criteria plus the travel-date staleness test. | `CaseManager` |
| POST | `/expediting/photos/{id}/retake` | Supersede a FAILED or EXPIRED photo with a fresh one. | `CaseManager`, `Traveler` |
| POST | `/expediting/applicants/{id}/prepared-forms` | Prepare the product's agency form against its ACTIVE revision. CREATE-with-supersede, OCC-guarded on the applicant. | `CaseManager` |
| GET | `/expediting/applicants/{id}/prepared-forms` | List a traveller's form preparations. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/prepared-forms/{id}/sign` | Sign a prepared form. | `CaseManager`, `Traveler` |
| POST | `/expediting/appointments` | Book a consulate interview. OCC-guarded on the slot. | `CaseManager` |
| GET | `/expediting/appointments` | List appointments; also the reverse-reachability read for applicant_id and slot_id. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| GET | `/expediting/appointments/{id}` | Read one appointment. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/appointments/{id}/reschedule` | Move a booking to another slot, or rebook after a no-show. | `CaseManager` |
| POST | `/expediting/appointments/{id}/outcome` | Record whether the traveller appeared. | `AgencyLiaison` |
| POST | `/expediting/orders/{id}/courier-legs` | Create an ordered physical hop for the passport book. | `CourierOps` |
| GET | `/expediting/orders/{id}/courier-legs` | List an order's hops in leg_index order. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/courier-legs/{id}/dispatch` | Hand the book to the courier for this hop. | `CourierOps` |
| POST | `/expediting/courier-legs/{id}/complete` | Close the hop as delivered or failed. | `CourierOps` |
| GET | `/expediting/orders/{id}/custody-events` | Read the append-only chain of custody; exactly one row has released_at null. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/orders/{id}/rfes` | Agency issues a request for evidence; pauses the SLA clock. | `AgencyLiaison` |
| GET | `/expediting/orders/{id}/rfes` | List an order's evidence requests. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/rfes/{id}/respond` | Respond to an open evidence request before its deadline. | `CaseManager`, `Traveler` |
| POST | `/expediting/rfes/{id}/adjudicate` | Agency judges the response, re-opens it, or lets it expire. | `AgencyLiaison` |
| POST | `/expediting/orders/{id}/agency-decision` | Agency approves or rejects the application. | `AgencyLiaison` |
| POST | `/expediting/orders/{id}/shipments` | Create the return delivery; escalates GROUND to OVERNIGHT close to the travel date. | `CourierOps` |
| GET | `/expediting/orders/{id}/shipments` | List an order's shipments. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| GET | `/expediting/shipments/{id}` | Read one shipment. | `PlatformAdmin`, `CaseManager`, `CourierOps`, `AgencyLiaison`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/shipments/{id}/delivery-attempt` | Record a delivery attempt; the capped failure falls back to hold-for-pickup. | `CourierOps` |
| PATCH | `/expediting/shipments/{id}/address` | Change the delivery region. Explicitly allowed while the passport is in agency custody. | `CaseManager`, `Traveler` |
| POST | `/expediting/shipments/{id}/pickup` | Record collection of a held shipment. | `CourierOps` |
| GET | `/expediting/orders/{id}/sla-segments` | Read the RUNNING/PAUSED partition of the agency clock in started_at order. | `PlatformAdmin`, `CaseManager`, `ComplianceOfficer`, `Traveler` |
| POST | `/expediting/_clock/set_current_utc` | Test-driving endpoint that sets the server's logical clock. Before any call the clock reads exactly 2026-05-01T00:00:00Z and MUST NOT fall back to wall-clock time. | `PlatformAdmin` |

---

## 5. Error Code Catalogue

The trigger condition for each error is specified in §2 and §3, alongside the rule it guards; the ladder position that decides precedence between two simultaneously-failing conditions is given in §2.9.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_NOT_ORDER_MEMBER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_AGENCY_CUSTODY_LOCK` | 409 |
| `ERR_ORDER_TERMINAL` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NATIONALITY_MISMATCH` | 422 |
| `ERR_CUSTODY_MISMATCH` | 409 |
| `ERR_LEG_SEQUENCE_VIOLATION` | 409 |
| `ERR_EMBASSY_CLOSED` | 409 |
| `ERR_OUT_OF_JURISDICTION` | 422 |
| `ERR_LEAD_TIME_VIOLATION` | 422 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_RESCHEDULE_CAP_EXCEEDED` | 409 |
| `ERR_RESUBMISSION_CAP_EXCEEDED` | 409 |
| `ERR_DOCUMENT_VALIDITY_INSUFFICIENT` | 422 |
| `ERR_PHOTO_RETAKE_CAP_EXCEEDED` | 409 |
| `ERR_FORM_REVISION_STALE` | 409 |
| `ERR_COURIER_ATTEMPT_CAP_EXCEEDED` | 409 |
| `ERR_DELIVERY_ATTEMPT_CAP_EXCEEDED` | 409 |
| `ERR_RFE_ROUND_CAP_EXCEEDED` | 409 |
| `ERR_RFE_DEADLINE_PASSED` | 409 |
| `ERR_TIER_NOT_AN_UPGRADE` | 422 |
| `ERR_UPGRADE_STAGE_CLOSED` | 409 |
| `ERR_STREAM_ALLOCATION_INVALID` | 422 |
| `ERR_APPLICANT_NOT_READY` | 409 |
| `ERR_SPLIT_PARTITION_MISMATCH` | 422 |
| `ERR_REQUIRED_DOCUMENTS_INCOMPLETE` | 409 |
| `ERR_RUSH_CUTOFF_MISSED` | 409 |
| `ERR_TRAVEL_DATE_INFEASIBLE` | 409 |
| `ERR_BALANCE_OUTSTANDING` | 402 |
| `ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED` | 422 |
