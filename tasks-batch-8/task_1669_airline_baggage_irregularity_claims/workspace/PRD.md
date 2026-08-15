# Airline Baggage Claims API — Product Requirements Document

## 1. Introduction

Every mishandled suitcase that arrives late, dented, or not at all becomes a file on a baggage service office's desk, and that file has a long life: a WorldTracer report is opened, interline carriers exchange tracing messages while the bag is hunted across the network, a courier is dispatched once the bag surfaces, the stranded passenger submits receipts for essentials, and eventually a claims adjuster computes liability, attributes a root cause, and pays the file closed. This document specifies the Airline Baggage Claims API, the system of record for that entire lifecycle — from the first irregularity report through tracing, recovery, delivery, interim expense reimbursement, damage repair-versus-replace decisions, settlement negotiation, final payment, and the station-level root-cause reporting that tells network operations where bags are being mishandled.

The API serves four distinct constituencies — front-line baggage service agents, claims adjusters, back-office administrators, and the travelling passengers themselves — and must keep their views of a claim mutually consistent while money, bag state, and file state move on interlocking tracks. All baggage resources are mounted under the `/baggage` path prefix. Two conventions pervade the design: monetary amounts are always carried as integer cents, and every time-dependent behavior is driven by a controllable logical clock rather than the wall clock, so that tracing timeouts, pickup windows, and expense eligibility behave deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `SystemAdmin`, `BaggageServiceAgent`, `ClaimsAdjuster`, and `Passenger`. Failure to provide valid, well-formed headers will result in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error (HTTP 400). Access to specific operations is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The four roles divide the work as follows. A `SystemAdmin` is the back-office administrator who owns configuration entities — stations, carriers, courier services, and repair vendors — and exclusively controls the logical clock. A `BaggageServiceAgent` is the front-line baggage service office agent who registers passengers, checks in bags, opens irregularity reports, records tracing messages, and dispatches and tracks deliveries. A `ClaimsAdjuster` is the claims adjudicator who assesses loss and damage, drives repair orders, adjudicates and pays expense claims, and computes and issues settlement payments. A `Passenger` is the travelling claimant, who submits interim expense claims and accepts or rejects settlement offers on their own reports.

Role identity is interpreted as follows. When `X-User-Role` is `SystemAdmin`, `BaggageServiceAgent`, or `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `Passenger`, `X-User-ID` is the `id` of the acting Passenger; ownership checks on any resource that references a Passenger compare the resource's `passenger_id` foreign-key field to `X-User-ID`. For the passenger-scoped operations — expense claim creation, settlement acceptance, and settlement rejection — a mismatch between `X-User-ID` and the report's `passenger_id` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources in the system — Stations, Carriers, Courier Services, Repair Vendors, Passengers, Bag Tags, Irregularity Reports, Delivery Dispatches, Repair Orders, Expense Claims, and Settlement Payments — carry a standard set of system-managed fields:

- `id` (string): A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): An ISO 8601 timestamp in UTC with three fractional digits (for example, `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- `updated_at` (string): An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified; it is refreshed upon any change to the resource's properties.
- `version` (integer): A system-managed integer that increments with every modification to the resource, enabling optimistic concurrency control where a write endpoint requires it.

Updates to derived fields — a station's counters, a courier's active dispatch count, a vendor's bench occupancy, a report's computed totals — are themselves mutations of the owning resource: they refresh `updated_at` and increment `version` just as direct edits do. The single exception to this convention is the Tracing Event, an append-only message record: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock

The server never consults the wall clock. Instead, a logical clock governs every time-dependent rule in the system: pickup-window guards, tracing timeouts, and delivery timestamps all evaluate against it. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A `SystemAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant, and the response reports the resulting `current_utc` together with a `swept_report_ids` array. Advancing the clock is not a passive act: setting it executes the tracing-timeout sweep described in §3.4, which can transition reports and bags as a side effect of time passing.

### 2.6. Cross-Entity Counters and Cascade Consistency

Several entities maintain derived counters that the server keeps in lockstep with the events that feed them, without requiring any explicit client request on the counter's owner. A Station tracks `open_report_count` (incremented when a report is filed at that station and decremented when that report reaches `CLOSED`), `recovered_bag_count` (incremented for each `LOCATED` tracing event recorded against the station), and `mishandled_report_count` (incremented when a closed report attributes its root cause to the station). A Courier Service tracks `active_dispatch_count`, the number of its dispatches in `DISPATCHED` or `FAILED_ATTEMPT` status. A Repair Vendor tracks `occupied_bench_slots` — orders in `INTAKE`, `REPAIR_IN_PROGRESS`, or `REPLACEMENT_PENDING` — and exposes `available_bench_slots` as the bench capacity minus the occupied count. Whenever one operation mutates more than one entity, every cascade listed in the workflow narratives of §3 applies atomically as part of that operation; each mutated resource refreshes its own `updated_at` and increments its own `version` per §2.4.

### 2.7. Nested Resource Retrieval

When an endpoint path contains a resource identifier, or a request body references other resources by foreign key, existence is validated before any business rule runs. For paths that chain identifiers, the system validates each identifier in sequential, left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. The same `ERR_NOT_FOUND` rejection applies to body-supplied references — `passenger_id`, `bag_tag_id`, `station_id`, the carrier ids inside `routing_carrier_ids`, `courier_service_id`, `vendor_id`, `report_id`, and `root_cause_station_id` — when they name resources that do not exist.

### 2.8. Money, Currency Conversion, and Rounding

All monetary values in the system are represented as integer cents. Liability caps, settlement offers, payment components, expense totals, repair estimates, and payouts are all integer-cent figures with no rounding applied to their sums or comparisons. The one place fractional money arises is currency conversion of foreign-denominated receipts: each receipt is converted individually and rounded half up to whole cents before any summation, and summing first and rounding afterward is expressly forbidden. Depreciated bag values are likewise rounded half up to whole cents, with the rounding applied once at the end of the decay computation. The single non-integer figure in the system is the station mishandled rate of §3.9, which is rounded half up to exactly two decimal places.

### 2.9. Optimistic Concurrency Control

Exactly one write operation is guarded by optimistic concurrency control: the creation of a Settlement Payment against a report (`POST /baggage/reports/{id}/settlement-payments`). Such a request must carry `expected_report_version`, a non-optional input field holding the report `version` the client last observed. If another writer has advanced the report's version since the client last read it — by creating or voiding a payment, or by re-offering a settlement after a rejection — the client's view of the report totals is stale, and the create is rejected with `ERR_STALE_REPORT_VERSION` (HTTP 412), preventing the client from settling against figures it has not observed. Endpoints not named here do not accept a version field.

### 2.10. Validation Order

Every request is screened against an ordered validation cascade, and the first failing check determines the rejection. The order is fixed:

1. **Header presence and form.** `X-User-ID` and `X-User-Role` must be present and well-formed, failing which the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. This check applies to all endpoints.
2. **Role authorization.** The caller's role must be listed among the endpoint's authorized roles, failing which the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`. This check applies to all endpoints.
3. **Ownership.** For the passenger-scoped operations — expense claim creation, settlement acceptance, and settlement rejection — `X-User-ID` must equal the report's `passenger_id`, failing which the request is rejected with `ERR_NOT_RESOURCE_OWNER`.
4. **Request body shape.** Required fields must be present, types must be correct, enum values must be valid, amounts must be non-negative, `tag_number` must match the ten-digit format, receipt arrays must be non-empty, and unknown or system-supplied fields must not appear in the payload; violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400). This check applies to all endpoints.
5. **Existence.** Path identifiers and body foreign keys must reference existing resources, failing which the request is rejected with `ERR_NOT_FOUND`.
6. **State.** The target resource must be in the required state for the operation, with machine-state checks evaluated first and the OCC `expected_report_version` check on settlement payment creation evaluated after them; wrong-state rejections carry the operation-specific state error of §3 (or the generic `ERR_INVALID_STATE_TRANSITION`, HTTP 409), and a stale version carries `ERR_STALE_REPORT_VERSION` (HTTP 412).
7. **Cross-entity referential rules.** A report's passenger must match its bag tag's passenger (`ERR_BAG_PASSENGER_MISMATCH`), a bag tag may have at most one non-`CLOSED` report (`ERR_BAG_ALREADY_REPORTED`), the courier must serve the report's filing station (`ERR_COURIER_ZONE_MISMATCH`), repair orders are allowed only for qualifying damage reports (`ERR_REPAIR_NOT_ALLOWED_FOR_TYPE`), and a settlement payment may not be created while the report has unadjudicated claims (`ERR_UNADJUDICATED_EXPENSE_CLAIMS`). These rules apply to report creation, dispatch creation, repair order creation, and settlement payment creation.
8. **Temporal rules.** Pickup windows must not begin before the logical clock (`ERR_PICKUP_IN_PAST`), dispatch windows on one courier must not conflict (`ERR_DISPATCH_WINDOW_CONFLICT`), and repair vendor bench capacity must not be exceeded (`ERR_VENDOR_CAPACITY_EXCEEDED`). These rules apply to dispatch creation, dispatch rescheduling, and repair order creation.
9. **Uniqueness and structural constraints.** `tag_number` must be unique (`ERR_DUPLICATE_TAG_NUMBER`), `report_reference` must be unique (`ERR_DUPLICATE_REPORT_REFERENCE`), at most one `ISSUED` settlement payment may exist per report (`ERR_ACTIVE_SETTLEMENT_PAYMENT_EXISTS`), and a repair order's dates must form a valid window (`ERR_REPAIR_WINDOW_INVALID`, HTTP 422). These rules apply to bag tag creation, report creation, settlement payment creation, and repair order creation.
10. **Fiscal caps.** Declared value and expense claim ceilings (`ERR_DECLARED_VALUE_EXCEEDS_MAX`, `ERR_EXPENSE_CLAIM_OVER_MAX`, both HTTP 422) apply to bag tag creation and expense claim creation.

Any state-machine transition attempted from a state that does not permit it — including transitions out of terminal states and repeated triggers — is rejected with `ERR_INVALID_STATE_TRANSITION` wherever §3 does not assign a more specific state error.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Stations, Carriers, Couriers, and Repair Vendors

Before the first bag can be reported missing, a `SystemAdmin` seeds the network's reference data. A **Station** is registered with its `station_code` — the IATA station code, such as JFK, treated as a unique business identifier — a display `name`, and `bags_handled_total`, the annualized number of bags handled at that station, which must be zero or more and later serves as the denominator of the station's mishandled rate. Three computed counters begin at zero on every new station: `open_report_count`, `recovered_bag_count`, and `mishandled_report_count`, maintained thereafter per §2.6.

A **Carrier** is registered with its `carrier_code` — the airline designator, such as AA, also unique — a `name`, and the `is_interline_partner` flag, which marks whether this carrier is an interline partner whose tracing messages are accepted into a file. Both the airline's own code and its partners' codes are registered here, since a bag's routing and its tracing traffic may span several carriers.

Delivery and repair capacity are likewise administrative data. A **Courier Service** is registered with a `name`, a `serves_station_ids` array naming the stations it delivers from, and `turnaround_buffer_minutes`, a buffer of zero or more minutes that is applied on both sides of every dispatch window when the system checks that courier for scheduling conflicts. Its `active_dispatch_count` starts at zero. A **Repair Vendor** is registered with a `name` and a `bench_capacity` — the maximum number of concurrently open repair orders, at least one — and begins life with `occupied_bench_slots` at zero and `available_bench_slots` equal to its full capacity.

### 3.2. Passenger Registration and Bag Check-In

A passenger enters the system when a `BaggageServiceAgent` — or a `SystemAdmin` — registers them with a `full_name` and a unique contact `email`. The optional `tier` field classifies the passenger as `STANDARD`, `PREMIUM`, or `ELITE`; when omitted it defaults to `STANDARD`. This tier later drives the daily cap on interim expense reimbursement for domestic reports (§3.6).

Checking a bag creates its **Bag Tag** record, an agent action that takes the ten-digit `tag_number`, the checking `passenger_id`, the `routing_carrier_ids` array ordered by travel sequence, the `is_international` flag indicating whether the routing crosses a country border, and the checked `weight_kg` in whole kilograms, which must be at least one. The last element of `routing_carrier_ids` is the delivering carrier, and that carrier becomes the liable carrier on any report filed against the bag. A passenger may declare excess value at check-in through `declared_value_cents`, which defaults to zero and may not exceed 500000 cents; a declared value above that ceiling is rejected with `ERR_DECLARED_VALUE_EXCEEDS_MAX` (HTTP 422). Tag numbers are unique across all bag tags — a duplicate is rejected with `ERR_DUPLICATE_TAG_NUMBER` — and a malformed tag number is rejected with `ERR_INVALID_REQUEST`.

A bag tag's `status` begins at `CHECKED` and moves through `MISHANDLED` and `IN_RECOVERY` as the irregularity lifecycle unfolds, ending in one of three terminal states: `DELIVERED`, `DELIVERED_DAMAGED`, or `CLAIMED_LOST`. The bag never transitions on its own; every move is a side effect of report and delivery events described in the following subsections.

### 3.3. Opening the Irregularity Report

When a bag fails to arrive intact and on time, a `BaggageServiceAgent` at the filing station opens an **Irregularity Report** — the WorldTracer file — by supplying a `report_reference` (the WorldTracer file reference, such as JFKAA00001, unique across all reports and guarded by `ERR_DUPLICATE_REPORT_REFERENCE`), the `passenger_id`, the `bag_tag_id`, the filing `station_id`, and the report `type`: `DELAYED`, `DAMAGED`, or `PILFERED`.

Two cross-entity guards protect file integrity at the moment of creation. The report's `passenger_id` must equal the referenced bag tag's `passenger_id` — a mismatch is rejected with `ERR_BAG_PASSENGER_MISMATCH` — and a bag tag may have at most one report that is not yet `CLOSED`, so filing a second open report against the same tag is rejected with `ERR_BAG_ALREADY_REPORTED`.

A report is born in `OPEN` status and immediately auto-transitions according to its type. A `DELAYED` report moves from `OPEN` to `TRACING`, and its bag flips from `CHECKED` to `MISHANDLED`. A `DAMAGED` or `PILFERED` report moves from `OPEN` to `DAMAGE_REVIEW`, and its bag flips from `CHECKED` to `DELIVERED_DAMAGED`. In both cases the filing station's `open_report_count` is incremented. The full set of report statuses is `OPEN`, `TRACING`, `FOUND_PENDING_DELIVERY`, `DELIVERY_IN_PROGRESS`, `DELIVERED`, `DECLARED_LOST`, `DAMAGE_REVIEW`, `CLAIM_REVIEW`, `SETTLEMENT_OFFERED`, `SETTLEMENT_ACCEPTED`, and the terminal `CLOSED`.

Creation also fixes the report's liability posture, computed once and stored. The `opened_on` field takes the date portion of the report's `created_at` and marks the start of the interim expense eligibility window. The `liability_regime` is `MONTREAL` when the bag tag's `is_international` is true and `DOMESTIC` otherwise. The `liable_carrier_id` is the last element of the bag tag's `routing_carrier_ids` — the delivering carrier carries the liability. The `effective_cap_cents` is the greater of a regime base cap and the bag's `declared_value_cents`: under the Montreal regime the base cap is a flat 170016 cents regardless of weight, while under the domestic regime the base cap scales linearly at 2500 cents per checked kilogram of `weight_kg` — so the same twenty-kilogram bag carries a base cap of 50000 cents domestically against 170016 cents internationally. Until the bag is delivered, `delivered_on` remains null. The assessment fields are likewise empty at filing: `contents_loss_cents`, `damage_repairable`, and `contents_damage_cents` remain null until an adjuster records them (§3.7, §3.8), and `repair_payout_cents` starts at zero until a repair order settles.

### 3.4. Tracing, Recovery, and the Lost-Bag Declaration

While a delayed-bag report sits in `TRACING`, the world's carriers exchange messages about the bag's whereabouts, and a `BaggageServiceAgent` records each WorldTracer message against the report as a **Tracing Event**. The agent supplies the sending `carrier_id`, the `station_id` the message reports from, and an `event_type` of `FORWARDED`, `LOCATED`, `ON_HAND_AT_STATION`, `IN_TRANSIT_TO`, `DELIVERY_ARRANGED`, or `MISSCAN_CORRECTED`, along with optional free-text `notes` (defaulting to an empty string) and an optional `occurred_at`; when `occurred_at` is omitted, the event is stamped with the current logical clock time. Recording a message on a report that is no longer in `TRACING` is rejected with `ERR_REPORT_NOT_TRACING`. Most event types simply enrich the file's history, but one of them changes everything.

A `LOCATED` event triggers the recovery cascade. The report moves from `TRACING` to `FOUND_PENDING_DELIVERY`; the bag moves from `MISHANDLED` to `IN_RECOVERY`; and the station named by the event's own `station_id` — the station where the bag surfaced — has its `recovered_bag_count` incremented. Note that the counting station is the one the event reports from, which need not be the filing station.

Some bags are never found. When the logical clock is advanced (§2.5), the tracing-timeout sweep examines every report still in `TRACING`: if at least 504 hours — twenty-one days — have elapsed between the report's `created_at` and the new clock time, and no `LOCATED` tracing event exists for the report, the report is swept to `DECLARED_LOST` and its bag moves from `MISHANDLED` to `CLAIMED_LOST`. The clock-setting response lists the affected reports in `swept_report_ids`.

### 3.5. Delivery Dispatch and Courier Tracking

Once a report reaches `FOUND_PENDING_DELIVERY`, a `BaggageServiceAgent` arranges the reunion by creating a **Delivery Dispatch**: the agent names the `report_id`, the `courier_service_id`, the `pickup_at` window start, the `travel_minutes` window length, and the `delivery_address`. The dispatch window runs from `pickup_at` through `pickup_at` plus `travel_minutes`, and `travel_minutes` must be at least one.

Four guards stand in front of dispatch creation, applied in the validation order of §2.10. The report must be in `FOUND_PENDING_DELIVERY`, failing which the request is rejected with `ERR_REPORT_NOT_AWAITING_DELIVERY`. The chosen courier must actually serve the report's filing station — the report's `station_id` must appear in the courier's `serves_station_ids` — failing which the request is rejected with `ERR_COURIER_ZONE_MISMATCH`. The `pickup_at` must be at or after the current logical clock time; a window in the past is rejected with `ERR_PICKUP_IN_PAST`. Finally, the new window must not conflict with any other non-terminal dispatch — one in `DISPATCHED` or `FAILED_ATTEMPT` status — on the same courier. Under buffer-expanded closed-interval semantics, a conflict exists exactly when the new window's start, shifted earlier by the courier's `turnaround_buffer_minutes`, falls strictly before the existing window's end, and at the same time the existing window's start falls strictly before the new window's end shifted later by the same buffer; two windows separated by exactly the buffer do not conflict. A conflicting window is rejected with `ERR_DISPATCH_WINDOW_CONFLICT`.

A freshly created dispatch starts in `DISPATCHED` with `attempt_count` at 1, the courier's `active_dispatch_count` is incremented, and the report advances from `FOUND_PENDING_DELIVERY` to `DELIVERY_IN_PROGRESS`. From there the courier's fate unfolds in one of three ways.

Confirming delivery is the happy path. Allowed only while the dispatch is `DISPATCHED` — otherwise the request is rejected with `ERR_INVALID_STATE_TRANSITION` — confirmation moves the dispatch to `DELIVERED` and cascades broadly: the report moves from `DELIVERY_IN_PROGRESS` to `DELIVERED`, the bag moves from `IN_RECOVERY` to `DELIVERED`, the report's `delivered_on` is stamped with the current logical clock date (closing the expense eligibility window for future adjudications), and the courier's `active_dispatch_count` is decremented.

Recording a failed attempt branches on the attempt number. While the dispatch's `attempt_count` is still below three, the failure moves the dispatch from `DISPATCHED` to `FAILED_ATTEMPT` and nothing else changes — the dispatch remains active and the courier's count is untouched. A failure recorded when `attempt_count` has reached three or more is permanent: the dispatch moves from `DISPATCHED` to `FAILED_PERMANENT`, the report falls back from `DELIVERY_IN_PROGRESS` to `FOUND_PENDING_DELIVERY` so it can accept a fresh dispatch, the bag remains `IN_RECOVERY`, and the courier's `active_dispatch_count` is decremented.

Rescheduling gives a failed attempt another chance. Only a dispatch in `FAILED_ATTEMPT` may be rescheduled — otherwise the request is rejected with `ERR_DISPATCH_NOT_RESCHEDULABLE`. The agent supplies `new_pickup_at`, which must be at or after the current logical clock time (again `ERR_PICKUP_IN_PAST`), and the window conflict check is re-run against the courier's other dispatches, excluding this dispatch's own window (again `ERR_DISPATCH_WINDOW_CONFLICT`). A successful reschedule returns the dispatch to `DISPATCHED`, increments `attempt_count` by one, and replaces `pickup_at` with `new_pickup_at`.

### 3.6. Interim Expense Claims and Reimbursement

A passenger separated from a delayed bag buys essentials and submits the receipts as an **Expense Claim**. The claim carries the `report_id` and a non-empty `receipts` array, each receipt recording the `incurred_on` purchase date, a free-text `description`, the `amount_minor` as an integer of at least one minor unit, and a `currency_code` of `USD`, `EUR`, or `JPY`. Only the report's owning passenger may file — a caller whose `X-User-ID` differs from the report's `passenger_id` is rejected with `ERR_NOT_RESOURCE_OWNER` — and only `DELAYED` reports in an expense-accepting status qualify: `TRACING`, `FOUND_PENDING_DELIVERY`, `DELIVERY_IN_PROGRESS`, `DELIVERED`, or `DECLARED_LOST`. A claim against a damaged or pilfered report, or against a delayed report in any other status, is rejected with `ERR_REPORT_NOT_ACCEPTING_EXPENSES`.

At submission the system computes two figures. The `claimed_total_cents` sums every receipt in the claim after converting each to US cents — a receipt in `USD` converts at a rate of 1.0, a receipt in `EUR` at 1.10, and a receipt in `JPY` at 0.0067 — where each receipt's conversion is individually rounded half up to whole cents before the sum is taken, per the rounding discipline of §2.8. This pre-cap total is validated at creation: a claim whose converted total exceeds 300000 cents is rejected with `ERR_EXPENSE_CLAIM_OVER_MAX` (HTTP 422). The `eligible_receipt_count` records how many of the receipts fall inside the eligibility window — from the report's `opened_on` through the earlier of the bag's `delivered_on` and the date five days after `opened_on`, both bounds inclusive; while `delivered_on` is still null, only the five-day bound applies. Receipts outside the window are excluded from reimbursement without error.

Adjudication belongs to the `ClaimsAdjuster`, who supplies a `decision` of `APPROVE` or `REJECT` for a claim in `SUBMITTED` — acting on a claim in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`. Approval computes and stores the claim's `reimbursable_total_cents` (null while the claim is `SUBMITTED`), and the computation forks on the report's `liability_regime`. For a `DOMESTIC` report, eligible receipts are grouped by their `incurred_on` day, each day's converted total is clipped at the passenger's tier daily cap — 7500 cents for `STANDARD`, 10000 cents for `PREMIUM`, 15000 cents for `ELITE` — and the reimbursable total is the sum of the clipped daily amounts; a single 20000-cent day therefore yields 7500 cents for a standard passenger. For a `MONTREAL` report, all eligible receipts pool into one converted sum clipped only at the 150000-cent pool cap, so the same receipts that would be shaved day by day domestically are reimbursed as a single pool internationally. The approved amount is added to the report's `expenses_approved_unpaid_cents`, and the claim moves from `SUBMITTED` to `APPROVED`. Rejection instead records the adjuster's `reject_reason` in the claim's `decision_reason` field and moves the claim from `SUBMITTED` to `REJECTED`, a terminal state; no reimbursable figure is computed on the reject path, and `decision_reason` remains null on claims that were never rejected.

An approved claim can be paid in two ways. While the file is still open, the adjuster may pay it as an interim reimbursement: the claim must be `APPROVED` (otherwise `ERR_CLAIM_NOT_PAYABLE`) and its report must not be `CLOSED` (otherwise `ERR_INVALID_STATE_TRANSITION`). Interim payment moves the claim from `APPROVED` to `PAID`, subtracts the reimbursable amount from the report's `expenses_approved_unpaid_cents`, and adds it to the report's `expenses_paid_cents`. Alternatively, an approved claim left unpaid is folded into the final settlement: when a Settlement Payment is created for the report, every `APPROVED` claim moves to `SETTLEMENT_EARMARKED` and its amount joins the payment's expense component; when that payment is later marked paid, the earmarked claims move to `PAID`; and if the payment is voided instead, they return to `APPROVED` (§3.8).

### 3.7. Damage Assessment and the Repair Workshop

Reports of type `DAMAGED` or `PILFERED` sit in `DAMAGE_REVIEW` until a `ClaimsAdjuster` assesses them. The damage assessment records a `repairable` flag and an optional `contents_damage_cents` amount, which defaults to zero; both are stored on the report as `damage_repairable` and `contents_damage_cents`. Assessing a report that is not in `DAMAGE_REVIEW` is rejected with `ERR_REPORT_NOT_IN_DAMAGE_REVIEW`. When the bag is not repairable, the assessment itself moves the report from `DAMAGE_REVIEW` to `CLAIM_REVIEW`. When the bag is repairable, the report stays in `DAMAGE_REVIEW` and the workshop path opens.

Sending a bag to the bench creates a **Repair Order**, an adjuster action naming the `report_id`, the `vendor_id`, the `intake_date` on which bench occupancy begins, the `promised_date` for completion, the bag's original `purchase_price_cents` (zero or more), the original `purchase_date`, and the vendor's `repair_estimate_cents` (zero or more). Repair orders exist only for `DAMAGED` reports in `DAMAGE_REVIEW` whose assessment marked the bag repairable: a request against a non-`DAMAGED` report or one whose `damage_repairable` is not true is rejected with `ERR_REPAIR_NOT_ALLOWED_FOR_TYPE`, and a request against a report no longer in `DAMAGE_REVIEW` is rejected with `ERR_REPAIR_NOT_IN_DAMAGE_REVIEW`. The dates must form a valid window — `promised_date` strictly after `intake_date`, and `purchase_date` on or before `intake_date` — failing which the request is rejected with `ERR_REPAIR_WINDOW_INVALID` (HTTP 422).

Bench capacity is a hard constraint, checked day by day. An order occupies its vendor's bench over the half-open range from `intake_date` up to but not including `promised_date`, so an order ending on a given day does not overlap one beginning that same day. If any day in that range would hold `bench_capacity` or more open repair orders at the vendor — orders in `INTAKE`, `REPAIR_IN_PROGRESS`, or `REPLACEMENT_PENDING` — creation is rejected with `ERR_VENDOR_CAPACITY_EXCEEDED`. A created order starts in `INTAKE`, and the vendor's `occupied_bench_slots` is incremented while `available_bench_slots` falls by one.

The repair-versus-replace decision is computed, never chosen. When the adjuster asks the system to decide an order — allowed only from `INTAKE`, otherwise `ERR_INVALID_STATE_TRANSITION` — the system first ages the bag: the number of full 365-day periods between `purchase_date` and `intake_date` is the bag's age in whole years, and the raw value is the original `purchase_price_cents` multiplied by 0.8 once for each of those years — a twenty-percent annual decay, compounding. The raw value is rounded half up to whole cents, and `depreciated_value_cents` is the greater of that rounded figure and a floor equal to ten percent of the purchase price, itself rounded half up to whole cents. The computed `decision` is `REPAIR` when the `repair_estimate_cents` is strictly less than seventy-five percent of the depreciated value, and `REPLACE` otherwise. Both figures remain null until this decide step runs, at which point the depreciated value and the decision are stored on the order. A `REPAIR` outcome moves the order from `INTAKE` to `REPAIR_IN_PROGRESS`; a `REPLACE` outcome moves it from `INTAKE` to `REPLACEMENT_PENDING`.

Completing the order settles the workshop's account. From `REPAIR_IN_PROGRESS`, completion moves the order to `REPAIR_SETTLED` and sets `payout_cents` to the lesser of the repair estimate and the depreciated value. From `REPLACEMENT_PENDING`, completion moves the order to `REPLACE_SETTLED` and sets `payout_cents` to the full depreciated value. Either way the vendor's bench slot is released — `occupied_bench_slots` decremented, `available_bench_slots` restored — and the settlement cascades into the report: the report moves from `DAMAGE_REVIEW` to `CLAIM_REVIEW`, its `repair_payout_cents` takes the order's `payout_cents`, and every other repair order of the same report still sitting in `INTAKE`, `REPAIR_IN_PROGRESS`, or `REPLACEMENT_PENDING` is moved to `CANCELLED`, each releasing its own vendor's bench slot. `REPAIR_SETTLED`, `REPLACE_SETTLED`, and `CANCELLED` are the terminal states of a repair order.

### 3.8. Settlement: From Claim Review to File Closure

A report can enter `CLAIM_REVIEW` by three doors, and the door matters because it determines the loss basis used at offer time. For a lost bag, the adjuster records the assessed `contents_loss_cents` on a report in `DECLARED_LOST` — assessing loss on a report in any other status is rejected with `ERR_REPORT_NOT_DECLARED_LOST` — and the report moves to `CLAIM_REVIEW` with the figure stored. For a damaged or pilfered bag, the report arrives from `DAMAGE_REVIEW`, either directly through a not-repairable damage assessment or indirectly when a repair order settles (§3.7). For a bag recovered late, the adjuster opens claim review on a report in `DELIVERED` — on any other status the request is rejected with `ERR_REPORT_NOT_DELIVERED`.

With the file in `CLAIM_REVIEW`, the adjuster makes the offer, supplying the `root_cause` — one of `MISCONNECT`, `BAGROOM_ERROR`, `LOADING_ERROR`, `TAGGING_ERROR`, or `SECURITY_HOLD` — and the `root_cause_station_id` attributing the failure to a station. Offering on a report not in `CLAIM_REVIEW` is rejected with `ERR_REPORT_NOT_IN_CLAIM_REVIEW`. The `settlement_offer_cents` is computed in a pinned order: first the loss basis is taken from the claim path — a report that entered review via `DECLARED_LOST` uses its stored `contents_loss_cents`; a `DAMAGED` report uses its `repair_payout_cents` plus its `contents_damage_cents` (treated as zero while null); a `PILFERED` report uses its `contents_damage_cents` alone (again zero while null); and a `DELAYED` report that was delivered uses zero. The offer is then the lesser of the report's `effective_cap_cents` and that loss basis. The offer and the root-cause attribution are stored on the report, `amount_payable_cents` is set equal to the offer, and the report moves from `CLAIM_REVIEW` to `SETTLEMENT_OFFERED`.

The offer belongs to the passenger. Only the owning passenger — `X-User-ID` equal to the report's `passenger_id`, otherwise `ERR_NOT_RESOURCE_OWNER` — and only while the report is `SETTLEMENT_OFFERED` (otherwise `ERR_SETTLEMENT_NOT_OFFERED`) may respond. Acceptance moves the report from `SETTLEMENT_OFFERED` to `SETTLEMENT_ACCEPTED`. Rejection sends the report back from `SETTLEMENT_OFFERED` to `CLAIM_REVIEW` for a revised offer, clearing `settlement_offer_cents`, `root_cause`, and `root_cause_station_id`, and resetting `amount_payable_cents` to zero.

Payment is the adjuster's final act, and it is the system's one OCC-guarded write (§2.9). Creating the **Settlement Payment** requires the report to be `SETTLEMENT_ACCEPTED` — otherwise the request is rejected with `ERR_SETTLEMENT_NOT_PAYABLE` — and the request must carry `expected_report_version` matching the report's current `version`; a stale expectation is rejected with `ERR_STALE_REPORT_VERSION` (HTTP 412). Two further guards apply: the report must have no expense claims still in `SUBMITTED` (otherwise `ERR_UNADJUDICATED_EXPENSE_CLAIMS`), and it must not already have a payment in `ISSUED` status (otherwise `ERR_ACTIVE_SETTLEMENT_PAYMENT_EXISTS`). The created payment is `ISSUED` and snapshots the money as it stands: `settlement_component_cents` takes the report's current `amount_payable_cents` in full, `expense_component_cents` sums the `reimbursable_total_cents` of every `APPROVED` expense claim on the report — and those claims move to `SETTLEMENT_EARMARKED` — and `amount_cents` is the sum of the two components. The report's `amount_payable_cents` is reduced by the settlement component, bringing it to zero, and the report's `version` is incremented by one. From the moment of the offer onward, a conservation invariant holds: the report's `settlement_offer_cents` always equals its `amount_payable_cents` plus the sum of `settlement_component_cents` over its payments in `ISSUED` or `PAID` status; `VOIDED` payments contribute nothing, because voiding restores the payable.

An issued payment has two exits. Marking it paid — allowed only from `ISSUED`, otherwise `ERR_INVALID_STATE_TRANSITION` — moves the payment to `PAID` and closes the file: the report moves from `SETTLEMENT_ACCEPTED` to `CLOSED`, every `SETTLEMENT_EARMARKED` expense claim on the report moves to `PAID`, the payment's `expense_component_cents` is added to the report's `expenses_paid_cents` and subtracted from its `expenses_approved_unpaid_cents`, the station named by `root_cause_station_id` has its `mishandled_report_count` incremented, and the filing station's `open_report_count` is decremented. Voiding instead — likewise only from `ISSUED` — moves the payment to `VOIDED` as compensation: the report's `amount_payable_cents` is restored by adding back the payment's `settlement_component_cents`, every earmarked claim returns to `APPROVED`, and the report's `version` is incremented by one. The report remains `SETTLEMENT_ACCEPTED`, and a superseding payment may be created against the fresh report version.

### 3.9. Station Irregularity Reporting

Network operations closes the loop with a per-station irregularity summary, available to every role. For the addressed station the summary reports its `station_id`, the live `open_report_count` of reports filed there that have not reached `CLOSED`, the `mishandled_report_count` of closed reports whose root cause was attributed to the station, and the `recovered_bag_count` of `LOCATED` tracing events recorded at the station. A `by_root_cause` breakdown groups those closed, attributed reports by their `root_cause`, omitting any cause whose count is zero. The headline figure, `mishandled_rate_per_1000`, is zero when the station's `bags_handled_total` is zero, and is otherwise one thousand times the `mishandled_report_count` divided by `bags_handled_total`, rounded half up to exactly two decimal places. No time window filters these counts; the summary reflects everything the system has recorded.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a Station, Carrier, Courier Service, Repair Vendor, Passenger, Bag Tag, Irregularity Report, Tracing Event, Settlement Payment, Delivery Dispatch, Repair Order, or Expense Claim) return a `201 Created` status code. Operations that act on an existing resource without creating a new one — assessments, settlement offers and responses, payment marking, dispatch marking and rescheduling, repair decisions and completions, claim adjudication and payment, and the logical clock — return a `200 OK` status code. List endpoints are paginated per §2.3 and support the filter query parameters described in §3 alongside `limit` and `offset`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; executes the tracing-timeout sweep | SystemAdmin |
| POST | `/baggage/stations` | Create a station | SystemAdmin |
| GET | `/baggage/stations/{id}` | Get a station | All roles |
| GET | `/baggage/stations` | List stations | All roles |
| GET | `/baggage/stations/{id}/irregularity-summary` | Root-cause station report: counts, recoveries, mishandled rate | All roles |
| POST | `/baggage/carriers` | Register a carrier (own or interline partner) | SystemAdmin |
| GET | `/baggage/carriers/{id}` | Get a carrier | All roles |
| POST | `/baggage/courier-services` | Register a courier service with served stations and turnaround buffer | SystemAdmin |
| GET | `/baggage/courier-services/{id}` | Get a courier service | All roles |
| GET | `/baggage/courier-services` | List courier services; `serves_station_ids` filter matches couriers serving that station | All roles |
| POST | `/baggage/repair-vendors` | Register a repair vendor with bench capacity | SystemAdmin |
| GET | `/baggage/repair-vendors/{id}` | Get a repair vendor | All roles |
| POST | `/baggage/passengers` | Register a passenger | BaggageServiceAgent, SystemAdmin |
| GET | `/baggage/passengers/{id}` | Get a passenger | All roles |
| POST | `/baggage/bag-tags` | Check in a bag (create the tag record) | BaggageServiceAgent |
| GET | `/baggage/bag-tags/{id}` | Get a bag tag | All roles |
| GET | `/baggage/bag-tags` | List bag tags; filter by `passenger_id` or by a carrier id contained in `routing_carrier_ids` | All roles |
| POST | `/baggage/reports` | Open a mishandled-bag report (WorldTracer file) | BaggageServiceAgent |
| GET | `/baggage/reports/{id}` | Get a report | All roles |
| GET | `/baggage/reports` | List reports with filters | All roles |
| POST | `/baggage/reports/{id}/tracing-events` | Record a WorldTracer tracing message from a carrier | BaggageServiceAgent |
| GET | `/baggage/tracing-events/{id}` | Get a tracing event | All roles |
| GET | `/baggage/tracing-events` | List tracing events with filters | All roles |
| POST | `/baggage/reports/{id}/assess-loss` | Record contents loss for a `DECLARED_LOST` report | ClaimsAdjuster |
| POST | `/baggage/reports/{id}/assess-damage` | Record damage assessment; not repairable moves the report to claim review | ClaimsAdjuster |
| POST | `/baggage/reports/{id}/open-claim-review` | Open claim review on a delivered (recovered late) report | ClaimsAdjuster |
| POST | `/baggage/reports/{id}/offer-settlement` | Compute and offer the settlement; records root-cause attribution | ClaimsAdjuster |
| POST | `/baggage/reports/{id}/accept-settlement` | Passenger accepts the settlement offer | Passenger |
| POST | `/baggage/reports/{id}/reject-settlement` | Passenger rejects the offer; report returns to claim review | Passenger |
| POST | `/baggage/reports/{id}/settlement-payments` | Create the final claim payment (OCC-guarded; supersedes a voided payment) | ClaimsAdjuster |
| GET | `/baggage/settlement-payments/{id}` | Get a settlement payment | All roles |
| GET | `/baggage/settlement-payments` | List settlement payments with filters | All roles |
| POST | `/baggage/settlement-payments/{id}/mark-paid` | Mark the final payment paid; closes the report file | ClaimsAdjuster |
| POST | `/baggage/settlement-payments/{id}/void` | Void an unpaid issued payment; compensation restores report payable and claim states | ClaimsAdjuster |
| POST | `/baggage/dispatches` | Dispatch a found bag to a courier for delivery | BaggageServiceAgent |
| GET | `/baggage/dispatches/{id}` | Get a dispatch | All roles |
| GET | `/baggage/dispatches` | List dispatches with filters | All roles |
| POST | `/baggage/dispatches/{id}/mark-delivered` | Courier confirmed delivery | BaggageServiceAgent |
| POST | `/baggage/dispatches/{id}/mark-failed` | Delivery attempt failed; third or later failure is permanent | BaggageServiceAgent |
| POST | `/baggage/dispatches/{id}/reschedule` | Reschedule a failed delivery attempt with a new pickup window | BaggageServiceAgent |
| POST | `/baggage/repair-orders` | Send a damaged bag to a repair vendor | ClaimsAdjuster |
| GET | `/baggage/repair-orders/{id}` | Get a repair order | All roles |
| GET | `/baggage/repair-orders` | List repair orders with filters | All roles |
| POST | `/baggage/repair-orders/{id}/decide` | Compute depreciation and the repair-vs-replace decision | ClaimsAdjuster |
| POST | `/baggage/repair-orders/{id}/complete` | Settle the repair order; releases the bench slot and moves the report to claim review | ClaimsAdjuster |
| POST | `/baggage/expense-claims` | Passenger submits an interim expense claim with receipts | Passenger |
| GET | `/baggage/expense-claims/{id}` | Get an expense claim | All roles |
| GET | `/baggage/expense-claims` | List expense claims with filters | All roles |
| POST | `/baggage/expense-claims/{id}/adjudicate` | Adjuster approves (computes the reimbursable total) or rejects the claim | ClaimsAdjuster |
| POST | `/baggage/expense-claims/{id}/pay` | Pay an approved claim as an interim reimbursement while the file is open | ClaimsAdjuster |

## 5. Error Code Catalogue

The following table lists every error identifier the API may return. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_REPORT_NOT_TRACING` | 409 Conflict |
| `ERR_REPORT_NOT_AWAITING_DELIVERY` | 409 Conflict |
| `ERR_REPORT_NOT_ACCEPTING_EXPENSES` | 409 Conflict |
| `ERR_REPORT_NOT_DELIVERED` | 409 Conflict |
| `ERR_REPORT_NOT_DECLARED_LOST` | 409 Conflict |
| `ERR_REPORT_NOT_IN_DAMAGE_REVIEW` | 409 Conflict |
| `ERR_REPORT_NOT_IN_CLAIM_REVIEW` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_OFFERED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PAYABLE` | 409 Conflict |
| `ERR_DISPATCH_NOT_RESCHEDULABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_PAYABLE` | 409 Conflict |
| `ERR_STALE_REPORT_VERSION` | 412 Precondition Failed |
| `ERR_BAG_PASSENGER_MISMATCH` | 409 Conflict |
| `ERR_BAG_ALREADY_REPORTED` | 409 Conflict |
| `ERR_COURIER_ZONE_MISMATCH` | 409 Conflict |
| `ERR_REPAIR_NOT_ALLOWED_FOR_TYPE` | 409 Conflict |
| `ERR_UNADJUDICATED_EXPENSE_CLAIMS` | 409 Conflict |
| `ERR_PICKUP_IN_PAST` | 409 Conflict |
| `ERR_DISPATCH_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_TAG_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_REFERENCE` | 409 Conflict |
| `ERR_ACTIVE_SETTLEMENT_PAYMENT_EXISTS` | 409 Conflict |
| `ERR_REPAIR_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_DECLARED_VALUE_EXCEEDS_MAX` | 422 Unprocessable Entity |
| `ERR_EXPENSE_CLAIM_OVER_MAX` | 422 Unprocessable Entity |
