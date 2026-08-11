# Sugar Coop Receiving API — Product Requirements Document

## 1. Introduction

Every autumn, a sugar-beet cooperative faces the same operational mountain: thousands of truckloads of freshly lifted beets arrive at receiving stations over a harvest window measured in weeks, and every load must be weighed, sampled for sugar content and field trash, piled for storage, and eventually paid for out of a shared campaign pool. Growers are not simple suppliers — they are member-owners of the cooperative, entitled to advances against the pool while the campaign is running and to a final settlement once the last pile has been reclaimed and the pool proceeds are known. The financial stakes are compounded by biology: sugar beets deteriorate in storage, and every pound lost to rot must be allocated fairly back to the members whose beets were in the pile.

This document specifies the Sugar Coop Receiving API, the system of record for one harvest campaign lifecycle. It covers the booking and scheduling of delivery slots at receiving stations, the weighbridge and quality-sampling workflow that converts a raw truckload into an adjusted, creditable tonnage, the management of piling grounds and the accounting of deterioration loss, and the cooperative's pool-payment machinery — provisional valuation, installment advances, transport allowances, and the final settlement statement that reconciles everything a member delivered against everything the pool earned. The API is designed around a segregation-of-duties role model (the technician who records a sugar reading may not verify it), an append-only payment ledger in which corrections are made by reversal rather than mutation, and optimistic concurrency on the fiscal resources where two writers could otherwise destroy an audit trail.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly across the API: authentication, response envelopes, pagination, resource identity, precision rules, concurrency control, and the domain invariants that every workflow in §3 relies on.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request whose `X-User-Role` header is missing or does not match one of the declared role names is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is syntactically valid but not on the endpoint's authorized-role list is rejected with `ERR_FORBIDDEN` (403).

The system recognizes six roles, spelled exactly as follows:

- `COOP_ADMIN` — cooperative administrator; manages campaigns, members, stations, and the logical clock.
- `SCHEDULER` — member-services scheduler; confirms bookings and manages slots.
- `MEMBER` — cooperative grower; books their own harvest slots and disputes or acknowledges their own settlement statements.
- `STATION_OPERATOR` — weighbridge and piling-ground operator; runs load tickets, piles, and loss-event recording.
- `QUALITY_TECH` — quality laboratory technician; collects samples, records results, and verifies lab results.
- `POOL_ACCOUNTANT` — cooperative pool accountant; manages pool accrual, installments, loss allocation, ledger reversals, and settlements.

Role identity is resolved as follows. When `X-User-Role` is `MEMBER`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` — a booking, a load ticket, a settlement statement, a ledger entry — compare the resource's `member_id` field to `X-User-ID`, and a `MEMBER` caller attempting to read or act on a resource whose `member_id` differs from their `X-User-ID` is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `COOP_ADMIN`, `SCHEDULER`, `STATION_OPERATOR`, `QUALITY_TECH`, or `POOL_ACCOUNTANT`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `recorded_by_user_id` on a `QualitySample` when a `QUALITY_TECH` records a result) but does not compare it to any entity's `id`.

One additional identity rule enforces segregation of duties in the laboratory: when a `QUALITY_TECH` attempts to verify a recorded sample, the verifier's `X-User-ID` must differ from the `recorded_by_user_id` captured when the result was recorded; a match is rejected with `ERR_SOD_VIOLATION` (403).

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned in one page; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped before the page begins and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — campaigns, members, stations, piles, bookings, load tickets, quality samples, pile allocations, loss events, payment pools, pool installments, and settlement statements — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter starting at creation and incremented by exactly 1 on every mutation of the resource, including mutations driven by cascading side effects from another resource's transition.

`PaymentLedgerEntry` is the deliberate exception to this convention. Because the ledger is an append-only event log in which corrections are posted as compensating `REVERSAL` entries rather than edits, a ledger entry carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. Weight, Tonnage, and Precision Conventions

The system works in pounds at the scale and in tons for capacity and payment. One ton is exactly 2000 pounds, and every conversion between the two units uses that factor. Percentages (sugar content, trash content, deterioration rates) are carried to 2 decimal places. Adjusted tonnages are rounded half-up to 4 decimal places. All monetary values are integer cents; wherever a calculation produces a fractional cent, the result is rounded half-up to a whole cent. Derived station tonnages that aggregate pound-denominated pile contents are divided by 2000 and rounded half-up to 4 decimal places.

The phrase "rounded half-up" is used throughout this document with its standard meaning: a value whose first discarded digit is 5 or greater rounds away from zero, otherwise toward zero.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. Endpoints not listed here do not accept a version field.

Creating a pool installment against a payment pool requires the request body to carry `expected_pool_version`, a non-optional field holding the `version` of the target `PaymentPool` as the client last observed it. If the value presented does not match the pool's current `version` — because another writer has advanced the pool's version since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from scheduling an installment against a pool state it has not observed.

Revising a disputed settlement statement requires the request body to carry `expected_settlement_version`, a non-optional field holding the `version` of the target `SettlementStatement` as the client last observed it. A mismatch with the statement's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Validation Order and Resource Existence

Incoming requests are validated in a fixed priority order, so that when several problems afflict the same request, the earliest check determines the error surfaced. Authentication comes first: a missing or undeclared `X-User-Role` produces `ERR_UNAUTHENTICATED` before anything else is examined. Role authorization follows, producing `ERR_FORBIDDEN` when the caller's role is not on the endpoint's list. Ownership and segregation-of-duties checks are third, again producing `ERR_FORBIDDEN` for member-scope violations and `ERR_SOD_VIOLATION` for self-verification. Only then are resource identifiers examined: every path identifier and every body foreign key (`booking_id`, `pile_id`, `ticket_id`, `campaign_id`, `station_id`) must resolve to an existing resource, otherwise the request fails with `ERR_NOT_FOUND` (404), and for nested paths the existence check proceeds strictly left to right so the first missing identifier in the path is the one reported. State-machine and request-shape checks run fifth (`ERR_INVALID_STATE`, `ERR_INVALID_REQUEST`, `ERR_TICKET_NOT_CREDITABLE`, `ERR_BOOKING_NOT_CONFIRMED`, `ERR_CAMPAIGN_NOT_OPEN`, `ERR_POOL_NOT_ACCRUING`, `ERR_PILE_NOT_FILLING`, `ERR_LAB_SAMPLE_REQUIRED`), optimistic-concurrency checks sixth (`ERR_STALE_VERSION`), member-compliance checks seventh (`ERR_MEMBER_SUSPENDED`), temporal-window checks eighth (`ERR_SLOT_OUTSIDE_WINDOW`, `ERR_WEIGH_WINDOW_CLOSED`, `ERR_SLOT_OVERLAP`, `ERR_SURVEY_BLACKOUT`), capacity and arithmetic checks ninth (`ERR_PILE_CAPACITY_EXCEEDED`, `ERR_PILE_STATION_MISMATCH`, `ERR_INVALID_WEIGHTS`, `ERR_TRASH_LIMIT_EXCEEDED`, `ERR_SHIPPED_WEIGHT_MISMATCH`, `ERR_MEASURED_WEIGHT_INVALID`), and fiscal checks last (`ERR_POOL_ACCRUAL_CAP_EXCEEDED`, `ERR_INSTALLMENT_PCT_INVALID`, `ERR_POOL_NO_SUGAR`, `ERR_REVERSAL_NOT_ALLOWED`).

### 2.8. Derived Totals and Ledger Reconciliation

Several aggregates on stations, members, piles, and pools are not stored as authoritative inputs but derived from underlying records, and the server recomputes them immediately whenever an underlying record changes. A station's `booked_tons` is the sum of `estimated_tons` over its bookings currently in `CONFIRMED` status. Its `received_tons` is the sum of `adjusted_net_tons_final` over its load tickets in `ACCEPTED` or `CREDITED` status. Its `stored_tons` is the sum of `stored_lbs` over all of its storage piles, divided by 2000 and rounded half-up to 4 decimal places. A pile's `stored_lbs` is the sum of `remaining_lbs` over its pile allocations in `ACTIVE` status. A member's `net_ledger_cents` is the sum of `amount_cents` over all of that member's `PaymentLedgerEntry` rows of every kind — `ADVANCE_CREDIT`, `FINAL_SETTLEMENT`, `TRANSPORT_CREDIT`, and `REVERSAL` — and a member's `deterioration_loss_lbs` is the sum of loss pounds allocated to that member across all `ALLOCATED` storage loss events.

The payment ledger itself is append-only. Every ledger entry is addressable by its `entry_id` and carries a `kind` field drawn from `ADVANCE_CREDIT`, `FINAL_SETTLEMENT`, `TRANSPORT_CREDIT`, or `REVERSAL`, together with the foreign keys appropriate to that kind (`member_id` and `pool_id` always; `installment_id` set for `ADVANCE_CREDIT` entries and null otherwise; `settlement_id` set for `FINAL_SETTLEMENT` and `TRANSPORT_CREDIT` entries and null otherwise). An error in a posted advance is never edited or deleted; it is compensated by posting a new entry of kind `REVERSAL` whose `amount_cents` is the negation of the original entry's amount and whose `reversal_of_id` references the original entry's `id`. A reversal is only permitted on an entry of kind `ADVANCE_CREDIT` that has not already been reversed, and only while the entry's pool is still in `ACCRUING` status; any other reversal attempt is rejected with `ERR_REVERSAL_NOT_ALLOWED` (409). Posting a reversal creates the new ledger entry and triggers recomputation of the affected member's `net_ledger_cents`.

### 2.9. The Logical Clock

The server maintains a logical clock that governs every time-dependent rule in this document: weigh windows, survey blackout windows, deterioration day counts, and seal/reclaim timestamps. The logical clock never falls back to wall-clock time. Its startup default, before any administrative call, is exactly 2026-05-01T00:00:00Z. A `COOP_ADMIN` may set the logical clock to a supplied `to_iso8601` instant through an admin-only test-driving capability; the capability returns the resulting `current_utc`. All "now" references in §3 mean the logical clock's current value.

## 3. Business Logic & Workflows

### 3.1. Campaign Setup, Stations, and the Membership Roster

A **campaign** represents one harvest season: it carries a display `name`, an inclusive harvest window delimited by `window_start` and `window_end`, and a provisional `base_price_cents_per_ton` that prices adjusted net tonnage for provisional valuation and installment entitlement. A `COOP_ADMIN` creates a campaign by supplying those four fields; the campaign begins life in `OPEN` status, and its creation automatically instantiates exactly one `PaymentPool` for it, with the pool's `campaign_id` set and the pool itself starting in `OPEN` status. A campaign's `status` walks a one-way path: `OPEN` to `CLOSED` to `SETTLING` to `SETTLED`, with `SETTLED` terminal. Closing a campaign is a `COOP_ADMIN` action available only when no booking of the campaign is in `CONFIRMED` or `IN_USE` status — a campaign with live booked tonnage refuses to close with `ERR_INVALID_STATE`. When the close succeeds, every booking of the campaign still sitting in `REQUESTED` or `WAITLISTED` is cancelled as a cascade, while bookings already `COMPLETED` are untouched, and the campaign's `version` increments by 1. The later transitions are system-driven: the campaign moves from `CLOSED` to `SETTLING` when its payment pool closes, and from `SETTLING` to `SETTLED` when every settlement statement of the campaign has reached `PAID`; each system transition increments the campaign's `version` by 1.

A **receiving station** is created by a `COOP_ADMIN` with a `name` and a `booking_capacity_tons` ceiling that must be greater than zero — the maximum total estimated tonnage that may be confirmed-booked at that station at any one time. The derived `booked_tons`, `received_tons`, and `stored_tons` figures described in §2.8 are exposed on the station resource and shift continuously as bookings, tickets, and piles change underneath it.

Membership administration is likewise a `COOP_ADMIN` function. Registering a member requires a `name`, a cooperative-unique `member_code` (for example `M-1001`; a duplicate code is a malformed request), and a `haul_distance_miles` figure — the one-way distance from farm to assigned station, which must be at least 0 and which later selects the member's transport rate band. A member begins `ACTIVE` and may cycle `ACTIVE` to `SUSPENDED` and back to `ACTIVE` without limit. Suspending a member is more than a flag flip: each of the member's bookings in `REQUESTED`, `WAITLISTED`, or `CONFIRMED` status is cancelled as a cascade, and for every `CONFIRMED` booking so cancelled the station's `booked_tons` is released and a waitlist promotion scan runs for that station (see §3.2). Both suspension and reinstatement increment the member's `version` by 1. A member's `net_ledger_cents` and `deterioration_loss_lbs` start at 0 and evolve per §2.8.

### 3.2. Booking the Harvest: Slots, Capacity, and the Waitlist

Before a single beet moves, a `MEMBER` reserves a delivery slot. Creating a booking requires the caller to supply `campaign_id`, `station_id`, `slot_start`, `slot_end`, and `estimated_tons` (which must be greater than zero); the booking's `member_id` is not taken from the request body but is set from the caller's `X-User-ID`, so a member can only ever book for themselves. The slot is a half-open interval: it begins at `slot_start` and ends at `slot_end`, which must be strictly after `slot_start`, and the end instant itself is excluded for overlap purposes. A new booking enters `REQUESTED` status. Booking creation requires the member to be `ACTIVE` — a suspended member's attempt is rejected with `ERR_MEMBER_SUSPENDED` — and the target campaign to be `OPEN`, otherwise `ERR_CAMPAIGN_NOT_OPEN`.

Confirmation is the `SCHEDULER`'s decision, and it applies four checks in this order: the booking's campaign must be `OPEN` (`ERR_CAMPAIGN_NOT_OPEN`); the booking's member must be `ACTIVE` (`ERR_MEMBER_SUSPENDED`); the slot must lie fully inside the campaign window, meaning `window_start` is at or before `slot_start` and `slot_end` is at or before `window_end` (`ERR_SLOT_OUTSIDE_WINDOW`); and the slot must not overlap any other `CONFIRMED` booking at the same station, where overlap is judged on half-open intervals — two slots overlap only if the new slot starts before the other's end and the other starts before the new slot's end, and mere adjacency (one slot's `slot_start` equal to the other's `slot_end`) is not overlap (`ERR_SLOT_OVERLAP`). Only after those four pass does the capacity check run, and capacity failure is deliberately not an error: if the station's `booked_tons` plus the booking's `estimated_tons` would exceed `booking_capacity_tons` — equality is allowed and confirms — the booking transitions to `WAITLISTED` instead of `CONFIRMED`, incrementing the booking's `version` by 1. When capacity does fit, the booking becomes `CONFIRMED`, the station's `booked_tons` increases by `estimated_tons`, and both the booking's `version` and the station's `version` increment by 1.

A confirmed booking is not locked. The owning member may reschedule it, which moves the booking from `CONFIRMED` back to `REQUESTED`: the caller must own the booking — its `member_id` must equal `X-User-ID`, else `ERR_FORBIDDEN` — and the replacement `slot_start` and `slot_end` must again lie fully inside the campaign window (`ERR_SLOT_OUTSIDE_WINDOW`). Rescheduling releases the held capacity (`booked_tons` decreases by `estimated_tons`, to be re-validated at the next confirm), replaces the slot values, and increments both the booking's and the station's `version` by 1. Cancellation is available to the owning member or a `SCHEDULER` from `REQUESTED`, `WAITLISTED`, or `CONFIRMED`; cancelling a `CONFIRMED` booking releases its `estimated_tons` from `booked_tons` and triggers a waitlist promotion scan at that station, while cancellations from `REQUESTED` or `WAITLISTED` touch only the booking's `version`. All cancellation paths increment the booking's `version` by 1, and the `CONFIRMED` cancellation also increments the station's `version` by 1.

The **waitlist promotion scan** runs whenever confirmed capacity is released at a station — a `CONFIRMED` booking cancelled, an `IN_USE` booking completed, or a member suspension cascade cancelling a `CONFIRMED` booking. Eligible candidates are bookings in `WAITLISTED` status at that station whose `estimated_tons` fit within the station's current free capacity (`booking_capacity_tons` minus current `booked_tons`). Candidates are ranked by `created_at` ascending, ties broken by the member's `member_code` ascending. The top-ranked eligible booking is promoted to `CONFIRMED`, the station's `booked_tons` increases by its `estimated_tons`, both resources' `version` counters increment, and then eligibility is re-evaluated with the updated `booked_tons`; the scan repeats until no eligible booking fits. If nothing fits, nothing is promoted and no error is raised.

Two further booking transitions are system-driven from the load-ticket workflow. When the first load ticket for a booking is weighed, the booking moves from `CONFIRMED` to `IN_USE`. When a load ticket for an `IN_USE` booking is accepted into a pile, the booking completes: it moves to `COMPLETED`, its `estimated_tons` are released from `booked_tons` (the slot is considered consumed), the waitlist promotion scan runs for the station, and both the booking's and the station's `version` increment. `COMPLETED` and `CANCELLED` are the booking's terminal states.

### 3.3. The Weighbridge: From Truck to Net Weight

When a truck arrives, a `STATION_OPERATOR` creates a **load ticket** by supplying the `booking_id` it fulfills. The booking must be in `CONFIRMED` or `IN_USE` status — any other state is rejected with `ERR_BOOKING_NOT_CONFIRMED` — and the booking's member must be `ACTIVE`, else `ERR_MEMBER_SUSPENDED`. The new ticket copies `member_id` and `station_id` from its booking and starts in `CREATED` status with `gross_weight_lbs`, `tare_weight_lbs`, and `net_weight_lbs` all null.

Weighing is a two-reading affair. The operator records `gross_weight_lbs` (the loaded truck on the scale) and `tare_weight_lbs` (the empty truck), and the system computes `net_weight_lbs` as the gross minus the tare. Two guards apply at weigh time. First, sanity: `tare_weight_lbs` must be greater than 0 and `gross_weight_lbs` must be strictly greater than `tare_weight_lbs`, otherwise the reading is rejected with `ERR_INVALID_WEIGHTS` (422). Second, timeliness: the logical clock must fall within the booking's weigh window, which opens thirty minutes (1800 seconds) before `slot_start` and closes one hour (3600 seconds) after `slot_end`; a weigh attempted outside that window is rejected with `ERR_WEIGH_WINDOW_CLOSED`. A successful weigh moves the ticket from `CREATED` to `WEIGHED`, flips the booking from `CONFIRMED` to `IN_USE` on the first weigh, and increments the ticket's `version`.

Scale errors happen, and the system supports a reweigh loop. Flagging a reweigh — permitted only while the logical clock is still within the same weigh window, else `ERR_WEIGH_WINDOW_CLOSED` — moves the ticket from `WEIGHED` to `REWEIGHING` and clears `gross_weight_lbs`, `tare_weight_lbs`, and `net_weight_lbs` back to null. Weighing again from `REWEIGHING` re-applies the same weight-sanity and window checks and recomputes `net_weight_lbs` from the new readings, returning the ticket to `WEIGHED`; each step increments the ticket's `version` by 1.

A ticket that will never be processed further can be voided from `CREATED`, `WEIGHED`, or `SAMPLED`, moving it to the terminal `VOIDED` state; the void action accepts an optional `reason` and increments the ticket's `version`.

### 3.4. Quality Sampling: Sugar, Trash, and Segregation of Duties

Every load is sampled. A `QUALITY_TECH` collects a **quality sample** against a ticket by supplying `ticket_id` and a `sample_type` of either `STATION_QUICK` (the station's rapid assay) or `LAB_VERIFY` (the laboratory verification that governs final payment). A fresh sample is `COLLECTED` with `sugar_pct` and `trash_pct` both null.

Recording a result is the technician's next step: they supply `sugar_pct` — which must be greater than 0 and at most 30 — and `trash_pct` — which must be at least 0 and at most 100. The sample's parent ticket must be in `WEIGHED` or `SAMPLED` status, else `ERR_INVALID_STATE`. Recording stamps the sample's `recorded_by_user_id` with the acting technician's `X-User-ID` and moves the sample to `RESULT_RECORDED`. If the ticket was `WEIGHED` at that moment, this first recorded sample triggers a cascade: the ticket moves to `SAMPLED`, its `provisional_trash_pct` and `provisional_sugar_pct` are copied from that triggering sample, and the system computes its `provisional_factor`, `provisional_adjusted_net_tons`, and `provisional_value_cents` per the calculation rules in §3.5. Both sample and ticket increment their `version` by 1.

Verification converts a recorded result into one the cooperative will pay on. The technician targets a sample by its `sample_id`. Only a `LAB_VERIFY` sample may be verified — attempting to verify a `STATION_QUICK` sample is rejected with `ERR_INVALID_STATE` — and the verifier must be a different person than the recorder: if the caller's `X-User-ID` equals the sample's `recorded_by_user_id`, the request is rejected with `ERR_SOD_VIOLATION`. A successful verify moves the sample from `RESULT_RECORDED` to its terminal `VERIFIED` state and increments its `version`.

Results can also be withdrawn. Invalidating a sample returns it from `RESULT_RECORDED` to `COLLECTED` and clears `sugar_pct`, `trash_pct`, and `recorded_by_user_id` to null. If the invalidated sample was the one that triggered its ticket's `SAMPLED` transition and no other sample of that ticket remains in `RESULT_RECORDED` or `VERIFIED`, the ticket reverts from `SAMPLED` to `WEIGHED` and all of its `provisional_*` fields are cleared to null; both resources' `version` counters increment.

### 3.5. From Weight to Value: Trash Deduction, Payment Factors, and Provisional Valuation

Three intertwined calculations convert a weighed, sampled load into a provisional dollar figure, and again at acceptance into final figures.

**Net weight and trash deduction.** The raw net weight is the gross minus the tare, in pounds. The trash deduction is parameterized by a trash percentage `t` — the ticket's `provisional_trash_pct` for the provisional computation or its `final_trash_pct` for the final one. The first 3.00 percent of trash is free: the deductible percentage is the amount by which `t` exceeds 3.00, or zero if `t` is at or below 3.00. Loads at or above 10.00 percent trash are penalized with a heavy multiplier of 1.5 applied to the deductible percentage; below 10.00 percent the multiplier is 1.0. The deducted percentage is the deductible percentage times the multiplier, but it is capped at `t` itself — the deduction can never consume more trash than the sample measured. The adjusted net tonnage is then the net weight in pounds divided by 2000 and multiplied by one minus the deducted percentage divided by 100, rounded half-up to 4 decimal places. The final adjusted weight in pounds, `adjusted_net_lbs_final`, is exactly the final adjusted tonnage multiplied by 2000.

**Payment factor.** The payment factor starts from a reference sugar content of 16.00 percent: the base factor is 1.00 plus four hundredths (a slope of 0.04) for every percentage point by which the measured sugar content differs from 16.00. The two variants diverge from there. The **provisional** factor, computed when the ticket enters `SAMPLED` from its first recorded sample of any type, clamps the base factor into the band from 0.70 to 1.30 inclusive and rounds half-up to 4 decimal places; no low-sugar penalty applies. The **final** factor, computed at acceptance from the latest `VERIFIED` `LAB_VERIFY` sample by `created_at`, is not clamped; instead, when the final sugar content falls below 13.00 percent, a penalty of 0.05 is subtracted from the base factor, and the result is rounded half-up to 4 decimal places. Because the two variants typically read different samples, the provisional and final factors for the same load commonly diverge.

**Provisional value.** When a ticket enters `SAMPLED`, its `provisional_value_cents` is the product of `provisional_adjusted_net_tons`, the campaign's `base_price_cents_per_ton`, and `provisional_factor`, rounded half-up to integer cents. This figure is what accrues against the pool when the ticket is later credited, and it is the basis of the member's share in installment advances.

### 3.6. Acceptance into the Pile: Final Figures and Allocations

Acceptance is the point of no return in the receiving workflow, and a `STATION_OPERATOR` performs it against a ticket in `SAMPLED` status by naming the target pile via `pile_id`. Five preconditions guard it, and they matter in narrative order. The ticket must have at least one `VERIFIED` sample whose `sample_type` is `LAB_VERIFY`, otherwise `ERR_LAB_SAMPLE_REQUIRED`. The resulting `final_trash_pct` — taken from the latest `VERIFIED` `LAB_VERIFY` sample by `created_at` — must be at most 20.00 percent exactly: 20.00 is accepted, 20.01 is rejected with `ERR_TRASH_LIMIT_EXCEEDED`. The target pile's `fill_status` must be `FILLING` (`ERR_PILE_NOT_FILLING`). The pile's `station_id` must equal the ticket's `station_id` (`ERR_PILE_STATION_MISMATCH`). And the pile must have room: its current `stored_lbs` plus the ticket's `adjusted_net_lbs_final` must not exceed the pile's `capacity_tons` multiplied by 2000, with equality allowed, else `ERR_PILE_CAPACITY_EXCEEDED`.

When acceptance succeeds, a chain of effects fires. The ticket's `final_trash_pct` and `final_sugar_pct` are copied from that latest verified lab sample; `final_factor`, `adjusted_net_tons_final`, and `adjusted_net_lbs_final` are computed per §3.5. A **pile allocation** is created for the receiving pile and is addressable thereafter by its `allocation_id`: its `ticket_id` and `pile_id` identify the load and the pile, its `member_id` is copied from the ticket, its `allocated_lbs` equals the ticket's `adjusted_net_lbs_final` at this moment, its `remaining_lbs` starts equal to `allocated_lbs`, and its `status` begins `ACTIVE`. The pile's `stored_lbs` increases by the allocated pounds, which triggers recomputation of the station's `received_tons` and `stored_tons`. The booking completes (`IN_USE` to `COMPLETED`), releasing its `estimated_tons` from the station's `booked_tons` and running the waitlist promotion scan. The ticket's `version` increments by 1.

The system also offers an explicit rejection path for dirty loads. A ticket in `SAMPLED` status may be rejected — the action takes an optional `reason` — but only when its `provisional_trash_pct` exceeds 20.00 percent; rejecting a load that is actually within the trash limit is a state error, `ERR_INVALID_STATE`. Rejection moves the ticket to the terminal `REJECTED` state while leaving the booking in `IN_USE`, so the member may deliver a replacement load against the same booking; the ticket's `version` increments.

### 3.7. Crediting the Pool: Accrual and the 110% Cap

An accepted ticket earns the member nothing until a `POOL_ACCOUNTANT` credits it to the pool. Crediting requires the ticket to be in `ACCEPTED` status — a credit attempt on a ticket in any other state is rejected with `ERR_TICKET_NOT_CREDITABLE` — and requires the pool of the ticket's campaign to be `ACCRUING`, else `ERR_POOL_NOT_ACCRUING`. A fiscal ceiling applies on top: the pool's `accrued_provisional_cents` plus the ticket's `provisional_value_cents` must not exceed 110 percent of the pool's `estimated_pool_value_cents` — that is, the estimated value multiplied by 1.10. A credit that would breach the cap is rejected with `ERR_POOL_ACCRUAL_CAP_EXCEEDED`. A successful credit moves the ticket from `ACCEPTED` to its terminal `CREDITED` state, adds the ticket's `provisional_value_cents` to the pool's `accrued_provisional_cents`, and increments both the ticket's and the pool's `version` by 1. The station's `received_tons` continues to count the ticket, since both `ACCEPTED` and `CREDITED` tickets feed that aggregate.

### 3.8. Piles and Deterioration: Seal, Survey, and Loss Allocation

A **storage pile** is created by a `STATION_OPERATOR` with a `station_id` placing it at a station and a `capacity_tons` that must be greater than zero. It begins with `fill_status` of `FILLING` and `condition_status` of `SOUND`, its `stored_lbs` at 0, and its `sealed_stored_lbs`, `sealed_at`, and `reclaim_started_at` awaiting future events.

Once a pile is full, the operator seals it, moving `fill_status` from `FILLING` to `SEALED`. Sealing snapshots the pile: `sealed_stored_lbs` captures the current `stored_lbs` and becomes the fixed basis for table-rate loss computation and resurvey validation, while `sealed_at` records the logical-clock timestamp of the seal. The pile's `version` increments. Later, the operator begins reclaim — moving `SEALED` to `RECLAIMING` and stamping `reclaim_started_at` with the logical clock — but only when no storage loss event for the pile is sitting in `DRAFT` or `CONFIRMED` with a blackout window that contains the current logical clock. Blackout containment is inclusive at both ends: the clock is blocked whenever it is at or after the event's `window_start` and at or before its `window_end`; a clock equal to `window_end` is still blocked. A blocked attempt is rejected with `ERR_SURVEY_BLACKOUT`. Completing the reclaim moves `RECLAIMING` to the terminal `EMPTY` state, but the operator must attest the shipped mass: the supplied `shipped_lbs` must equal the sum of `remaining_lbs` over the pile's `ACTIVE` allocations exactly, otherwise `ERR_SHIPPED_WEIGHT_MISMATCH`. On success, every allocation of the pile transitions to `DEPLETED` — each one's `remaining_lbs` is preserved as the loss-adjusted creditable weight — the pile's `stored_lbs` is recomputed and becomes 0, the station's `stored_tons` recomputes, and the pile's `version` increments.

Deterioration is tracked through **storage loss events**. An operator creates one against a sealed pile — the pile's `fill_status` must be `SEALED` both at creation and again at confirmation, else `ERR_INVALID_STATE` — supplying `pile_id`, a `method` of `TABLE_RATE` or `RESURVEY`, a `survey_at` timestamp, and the blackout `window_start` and `window_end` that will guard reclaim while the event is open. The event begins in `DRAFT` with `loss_lbs` and `unallocated_lbs` null. For the `RESURVEY` method, `measured_remaining_lbs` — the surveyor's measurement of the mass still in the pile — must be supplied at creation, and a create request that omits it is rejected with `ERR_INVALID_REQUEST`; for `TABLE_RATE` it is ignored.

Confirmation, addressed by the event's `loss_event_id`, computes the loss. The day count is the whole number of days between sealing and survey: the difference between `survey_at` and the pile's `sealed_at`, divided by 86400 seconds and rounded down. Under `TABLE_RATE`, the loss is the pile's `sealed_stored_lbs` multiplied by a daily deterioration rate of 0.0008 and by the day count, rounded half-up to 2 decimal places — a projection independent of any measurement. Under `RESURVEY`, the loss is the pile's `sealed_stored_lbs`, minus the sum of `loss_lbs` over the pile's prior `CONFIRMED` or `ALLOCATED` events, minus the supplied `measured_remaining_lbs`; the result must be at least 0, and a negative result is rejected with `ERR_MEASURED_WEIGHT_INVALID`. For the same pile state the two variants generally produce different `loss_lbs`. Confirming stores the computed `loss_lbs`, moves the event from `DRAFT` to `CONFIRMED`, recomputes the pile's `condition_status`, and increments the event's `version`. The condition recompute compares cumulative confirmed loss against 5.00 percent of `sealed_stored_lbs`: a confirmation with positive `loss_lbs` whose cumulative confirmed total stays at or under 5.00 percent moves a `SOUND` pile to `DETERIORATING`; a confirmation that pushes cumulative confirmed loss over 5.00 percent moves the pile — whether `SOUND` or already `DETERIORATING` — to the terminal `LOSS_DECLARED`. Each condition transition increments the pile's `version`.

Allocation is a `POOL_ACCOUNTANT` action that distributes a confirmed event's loss across the pile's `ACTIVE` allocations and cascades three levels deep. The candidates are the pile's allocations in `ACTIVE` status; if their `remaining_lbs` sums to zero, nothing is distributed, the event's `unallocated_lbs` is set to the full `loss_lbs` (a zero-quantity guard that avoids any division), and the event moves to `ALLOCATED`. Otherwise each candidate's share is computed as the event's `loss_lbs` multiplied by the candidate's `remaining_lbs` and divided by the total remaining, floored toward zero to 2 decimal places. The remainder — the event's `loss_lbs` minus the sum of floored shares — is then distributed in 0.01-pound units to allocations ordered by `remaining_lbs` descending with ties broken by allocation `created_at` ascending, one unit per pass, largest first. Each allocation's `remaining_lbs` is reduced by its share plus any remainder units received. Every reduced allocation triggers a recompute of the pile's `stored_lbs`; the pile's recompute in turn triggers a recompute of the station's `stored_tons`; and each member's `deterioration_loss_lbs` is incremented by the total pounds allocated to their allocations. The event's `unallocated_lbs` records `loss_lbs` minus the total distributed — 0 in every case except the zero-remaining guard. Multiple events on the same pile are processed in chronological order of `survey_at`, ties broken by event `created_at` ascending; each event's allocation reduces `remaining_lbs`, which is the basis of the next event, so evaluation order is pinned and observable. Allocation moves the event from `CONFIRMED` to its terminal `ALLOCATED` state and increments its `version`.

### 3.9. Pool Lifecycle and Installment Advances

The **payment pool** is created alongside its campaign in `OPEN` status, with `estimated_pool_value_cents` and `gross_pool_value_cents` null, `accrued_provisional_cents` at 0, and `final_price_cents_per_lb` null. A `POOL_ACCOUNTANT` opens accrual by declaring `estimated_pool_value_cents`, which must be greater than zero (`ERR_INVALID_REQUEST` otherwise) and requires the campaign still `OPEN` (`ERR_CAMPAIGN_NOT_OPEN` otherwise); the pool moves `OPEN` to `ACCRUING` and its `version` increments. The declared estimate is the basis for both installment targets and the 110 percent accrual cap of §3.7.

While the pool is `ACCRUING`, the accountant schedules **pool installments** against it. Creating an installment takes `pct_of_estimated` — the percentage of the estimated pool value to distribute as advances, which must be greater than 0 and at most 100, else `ERR_INSTALLMENT_PCT_INVALID` — and, per §2.6, an `expected_pool_version` that must match the pool's current `version`, else `ERR_STALE_VERSION` (412). The installment's `target_amount_cents` is the percentage divided by 100 and multiplied by `estimated_pool_value_cents`, rounded half-up to integer cents. The installment begins `SCHEDULED` with `distributed_amount_cents` at 0; creating it increments the pool's `version` by 1.

Issuing a scheduled installment runs the **installment waterfall**. The pool must be `ACCRUING`, else `ERR_POOL_NOT_ACCRUING`. Each member's entitlement basis, E_m, is the sum of `provisional_value_cents` over that member's `CREDITED` tickets for the campaign; members with an E_m of zero are excluded entirely. Each member's raw advance is the installment's `target_amount_cents` multiplied by their E_m and divided by the sum of E_m over all eligible members, then floored to integer cents. The remainder — the target minus the sum of floored advances — is distributed one cent at a time to members ordered by E_m descending, ties broken by `member_code` ascending. Each member's advance is then capped: it may not exceed the member's E_m minus the member's already-advanced amount for this pool, where already-advanced is the member's net `ADVANCE_CREDIT` (advances plus any reversals). One `ADVANCE_CREDIT` ledger entry is created per member whose final advance is greater than zero, with `member_id`, `pool_id`, and `installment_id` set; each paid member's `net_ledger_cents` is recomputed; the installment's `distributed_amount_cents` records the sum of created advances, which is at most the target when caps bind — any undistributable residual stays in the pool. Issuing moves the installment to its terminal `ISSUED` state and increments its `version`.

### 3.10. Pool Close, Final Price, and Settlement Statements

Closing the pool is the pivot from accrual to settlement, and a `POOL_ACCOUNTANT` may close it only when four conditions hold: the campaign is `CLOSED` (`ERR_INVALID_STATE`); no load ticket of the campaign remains in `CREATED`, `WEIGHED`, `REWEIGHING`, `SAMPLED`, or `ACCEPTED` (`ERR_INVALID_STATE`); every storage pile holding allocations from the campaign's tickets is `EMPTY` (`ERR_INVALID_STATE`); and the total post-loss sugar pounds over the campaign's `CREDITED` tickets is greater than zero (`ERR_POOL_NO_SUGAR`). The accountant declares `gross_pool_value_cents` — the actual proceeds the pool realized — at close.

The **final pool price** is computed at close. For each `CREDITED` ticket, its remaining pounds are the sum of `remaining_lbs` over its pile allocations, and its sugar pounds are that remaining mass multiplied by its `final_sugar_pct` divided by 100, rounded half-up to 2 decimal places. The total sugar pounds sum this per-ticket figure over `CREDITED` tickets only — `REJECTED`, `VOIDED`, and `ACCEPTED`-but-not-`CREDITED` tickets are excluded. The pool's `final_price_cents_per_lb` is `gross_pool_value_cents` divided by the total sugar pounds, rounded half-up to 4 decimal places. Closing moves the pool from `ACCRUING` to `CLOSED`, drives the campaign from `CLOSED` to `SETTLING`, and increments the pool's `version`.

With a closed pool, the accountant generates **settlement statements** for every member with at least one `CREDITED` ticket in the campaign, supplying the `campaign_id`. Generation computes, per member: `sugar_lbs` as the sum of the member's per-ticket sugar pounds computed exactly as in the final price; a raw gross entitlement of `sugar_lbs` multiplied by the pool's `final_price_cents_per_lb`, rounded half-up to integer cents; and `transport_credit_cents` per the transport allowance below. A rounding delta almost always appears because per-member rounding loses or gains cents against the declared gross: the delta between `gross_pool_value_cents` and the sum of raw gross entitlements is absorbed by the member with the largest raw gross entitlement — ties broken by `member_code` ascending — whose `gross_entitlement_cents` becomes their raw gross plus the delta, while all other members keep their raw gross. Each statement snapshots `price_cents_per_lb` from the pool at generation time and begins in `DRAFT` status.

The **transport allowance** compensates haul distance and is computed per member per `CREDITED` ticket. The member's `haul_distance_miles` selects a rate band in cents per adjusted net ton: under 15 miles pays 120; at least 15 and under 40 miles pays 180; at least 40 and under 80 miles pays 240; 80 miles or more pays 300. The bands are left-closed and right-open, so exactly 15 miles falls in the 180 band. Each ticket's allowance is its `adjusted_net_tons_final` multiplied by the band rate, rounded half-up to integer cents; the statement's `transport_credit_cents` is the sum of those per-ticket rounded allowances. The rounding order is pinned: round each ticket first, then sum — summing first and rounding once is a different, non-conformant algorithm.

Issuing a statement — available while the pool is `CLOSED`, else `ERR_INVALID_STATE` — completes the member's arithmetic. `advances_posted_cents` is the member's net `ADVANCE_CREDIT` for the pool, counting advance entries and any reversal entries. `final_payment_cents` is `gross_entitlement_cents` minus `advances_posted_cents`, and it may be negative when advances exceeded entitlement — a clawback. `total_payment_cents` is `final_payment_cents` plus `transport_credit_cents`. The statement moves from `DRAFT` to `ISSUED` and its `version` increments. One invariant is pinned across the whole settlement: the sum over members of `advances_posted_cents` plus `final_payment_cents` equals `gross_pool_value_cents` exactly.

The statement's remaining lifecycle handles member response. The owning member — and only the owning member, else `ERR_FORBIDDEN` — may dispute an `ISSUED` statement, moving it to `DISPUTED` with an optional `reason`. The accountant may then revise it, which pulls the statement from `DISPUTED` back to `DRAFT` for regeneration of its computed fields; per §2.6 the revision request must carry `expected_settlement_version` matching the statement's current `version`, else `ERR_STALE_VERSION` (412), and an optional `note` may accompany the revision. Alternatively the owning member may acknowledge an `ISSUED` statement, moving it to `ACKNOWLEDGED`. Finally, the accountant marks an `ACKNOWLEDGED` statement paid: a `FINAL_SETTLEMENT` ledger entry is created for `final_payment_cents` with `settlement_id` set; when `transport_credit_cents` is greater than zero a separate `TRANSPORT_CREDIT` entry of that amount is created with `settlement_id` set; the member's `net_ledger_cents` is recomputed; and if every settlement statement of the pool has now reached `PAID`, the pool moves from `CLOSED` to `SETTLED` and the campaign from `SETTLING` to `SETTLED` in a compound transition. Each of these steps increments the statement's `version` by 1, and the pool's and campaign's compound transitions each increment their own `version` by 1.

## 4. Endpoint Definitions

All resources are mounted under `/api`. Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, recordings, confirmations — return `200 OK`. Reads return `200 OK`. All error responses use the envelope of §2.2 with a 4xx status from §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | COOP_ADMIN |
| POST | `/api/campaigns` | Create a campaign (starts OPEN); auto-creates its PaymentPool in OPEN | COOP_ADMIN |
| GET | `/api/campaigns/{campaign_id}` | Get a campaign | COOP_ADMIN, STATION_OPERATOR, QUALITY_TECH, SCHEDULER, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/campaigns/{campaign_id}/close` | Close a campaign (OPEN to CLOSED); cancels REQUESTED/WAITLISTED bookings | COOP_ADMIN |
| GET | `/api/campaigns/{id}/pools` | List the campaign's pools (0 or 1 element) | COOP_ADMIN, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/members` | Register a cooperative member (starts ACTIVE) | COOP_ADMIN |
| GET | `/api/members/{member_id}` | Get a member; MEMBER role may only read its own id | COOP_ADMIN, STATION_OPERATOR, SCHEDULER, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/members/{member_id}/suspend` | Suspend a member (ACTIVE to SUSPENDED); cascades booking cancellations and waitlist promotion | COOP_ADMIN |
| POST | `/api/members/{member_id}/reinstate` | Reinstate a suspended member (SUSPENDED to ACTIVE) | COOP_ADMIN |
| POST | `/api/stations` | Create a receiving station | COOP_ADMIN |
| GET | `/api/stations/{station_id}` | Get a station with computed booked/received/stored tons | COOP_ADMIN, STATION_OPERATOR, SCHEDULER, POOL_ACCOUNTANT, MEMBER |
| GET | `/api/stations/{id}/piles` | List piles at a station | COOP_ADMIN, STATION_OPERATOR, SCHEDULER, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/piles` | Create a storage pile (FILLING / SOUND) | STATION_OPERATOR |
| GET | `/api/piles/{pile_id}` | Get a pile | COOP_ADMIN, STATION_OPERATOR, SCHEDULER, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/piles/{pile_id}/seal` | Seal a pile (FILLING to SEALED); snapshots sealed_stored_lbs and sealed_at | STATION_OPERATOR |
| POST | `/api/piles/{pile_id}/begin-reclaim` | Begin reclaim (SEALED to RECLAIMING); blocked by inclusive survey blackout windows | STATION_OPERATOR |
| POST | `/api/piles/{pile_id}/complete-reclaim` | Complete reclaim (RECLAIMING to EMPTY); shipped_lbs must equal remaining allocation mass | STATION_OPERATOR |
| GET | `/api/piles/{id}/loss-events` | List loss events for a pile | COOP_ADMIN, STATION_OPERATOR, POOL_ACCOUNTANT |
| POST | `/api/bookings` | Member creates a harvest booking (REQUESTED); member_id derived from X-User-ID | MEMBER |
| GET | `/api/bookings/{booking_id}` | Get a booking; MEMBER role only for own bookings | COOP_ADMIN, STATION_OPERATOR, SCHEDULER, POOL_ACCOUNTANT, MEMBER |
| GET | `/api/bookings` | List bookings with filters | COOP_ADMIN, STATION_OPERATOR, SCHEDULER, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/bookings/{booking_id}/confirm` | Confirm a REQUESTED booking; capacity overflow routes to WAITLISTED | SCHEDULER |
| POST | `/api/bookings/{booking_id}/reschedule` | Owning member moves a CONFIRMED booking back to REQUESTED with a new slot | MEMBER |
| POST | `/api/bookings/{booking_id}/cancel` | Cancel a booking from REQUESTED, WAITLISTED, or CONFIRMED | MEMBER, SCHEDULER |
| POST | `/api/tickets` | Create a load ticket against a CONFIRMED or IN_USE booking | STATION_OPERATOR |
| GET | `/api/tickets/{ticket_id}` | Get a ticket; MEMBER role only for own tickets | COOP_ADMIN, STATION_OPERATOR, QUALITY_TECH, SCHEDULER, POOL_ACCOUNTANT, MEMBER |
| GET | `/api/tickets` | List tickets with filters and pagination | COOP_ADMIN, STATION_OPERATOR, QUALITY_TECH, SCHEDULER, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/tickets/{ticket_id}/weigh` | Weigh a ticket (CREATED to WEIGHED or REWEIGHING to WEIGHED) | STATION_OPERATOR |
| POST | `/api/tickets/{ticket_id}/reweigh` | Flag scale error (WEIGHED to REWEIGHING); clears weights | STATION_OPERATOR |
| POST | `/api/tickets/{ticket_id}/accept` | Accept a SAMPLED ticket into a pile; computes final factor and creates the PileAllocation | STATION_OPERATOR |
| POST | `/api/tickets/{ticket_id}/reject` | Reject a SAMPLED ticket whose provisional trash exceeds 20.00 | STATION_OPERATOR |
| POST | `/api/tickets/{ticket_id}/void` | Void a ticket from CREATED, WEIGHED, or SAMPLED | STATION_OPERATOR |
| POST | `/api/tickets/{ticket_id}/credit` | Credit an ACCEPTED ticket to the pool (ACCEPTED to CREDITED) | POOL_ACCOUNTANT |
| POST | `/api/samples` | Collect a quality sample for a ticket | QUALITY_TECH |
| POST | `/api/samples/{sample_id}/record-result` | Record sugar/trash results (COLLECTED to RESULT_RECORDED); may drive ticket WEIGHED to SAMPLED | QUALITY_TECH |
| POST | `/api/samples/{sample_id}/verify` | Verify a LAB_VERIFY sample (RESULT_RECORDED to VERIFIED); verifier must differ from recorder | QUALITY_TECH |
| POST | `/api/samples/{sample_id}/invalidate` | Invalidate a recorded result (RESULT_RECORDED to COLLECTED) | QUALITY_TECH |
| GET | `/api/tickets/{id}/samples` | List samples for a ticket | COOP_ADMIN, STATION_OPERATOR, QUALITY_TECH, POOL_ACCOUNTANT, MEMBER |
| GET | `/api/pools/{pool_id}` | Get a pool (includes version for OCC) | COOP_ADMIN, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/pools/{pool_id}/open-accrual` | Open accrual (OPEN to ACCRUING) declaring the estimated pool value | POOL_ACCOUNTANT |
| POST | `/api/pools/{pool_id}/close` | Close the pool (ACCRUING to CLOSED) declaring gross value; computes final price | POOL_ACCOUNTANT |
| POST | `/api/pools/{id}/installments` | Create a pool installment (OCC-guarded by expected_pool_version) | POOL_ACCOUNTANT |
| GET | `/api/pools/{id}/installments` | List installments of a pool | COOP_ADMIN, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/installments/{installment_id}/issue` | Issue a SCHEDULED installment; creates ADVANCE_CREDIT ledger entries per the installment waterfall | POOL_ACCOUNTANT |
| POST | `/api/loss-events` | Create a loss event on a pile (DRAFT); pile must be SEALED | STATION_OPERATOR |
| POST | `/api/loss-events/{loss_event_id}/confirm` | Confirm a loss event (DRAFT to CONFIRMED); computes loss_lbs per method variant; updates pile condition | STATION_OPERATOR |
| POST | `/api/loss-events/{loss_event_id}/allocate` | Allocate a confirmed loss across pile allocations (CONFIRMED to ALLOCATED); cascades to pile, station, members | POOL_ACCOUNTANT |
| GET | `/api/pile-allocations/{allocation_id}` | Get a pile allocation | COOP_ADMIN, STATION_OPERATOR, POOL_ACCOUNTANT, MEMBER |
| GET | `/api/pile-allocations` | List pile allocations with filters | COOP_ADMIN, STATION_OPERATOR, POOL_ACCOUNTANT, MEMBER |
| GET | `/api/ledger-entries/{entry_id}` | Get a ledger entry | COOP_ADMIN, POOL_ACCOUNTANT, MEMBER |
| GET | `/api/ledger-entries` | List ledger entries with filters | COOP_ADMIN, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/ledger-entries/{entry_id}/reverse` | Reverse an unreversed ADVANCE_CREDIT entry while its pool is ACCRUING; creates a REVERSAL entry | POOL_ACCOUNTANT |
| POST | `/api/settlements/generate` | Generate DRAFT settlement statements for all members with CREDITED tickets in the campaign | POOL_ACCOUNTANT |
| GET | `/api/settlements/{settlement_id}` | Get a settlement statement; MEMBER role only for own statements | COOP_ADMIN, POOL_ACCOUNTANT, MEMBER |
| GET | `/api/settlements` | List settlement statements with filters | COOP_ADMIN, POOL_ACCOUNTANT, MEMBER |
| POST | `/api/settlements/{settlement_id}/issue` | Issue a DRAFT statement (computes advances_posted and final_payment) | POOL_ACCOUNTANT |
| POST | `/api/settlements/{settlement_id}/dispute` | Owning member disputes an ISSUED statement | MEMBER |
| POST | `/api/settlements/{settlement_id}/revise` | Pull a DISPUTED statement back to DRAFT (OCC-guarded by expected_settlement_version) | POOL_ACCOUNTANT |
| POST | `/api/settlements/{settlement_id}/acknowledge` | Owning member acknowledges an ISSUED statement | MEMBER |
| POST | `/api/settlements/{settlement_id}/mark-paid` | Mark an ACKNOWLEDGED statement paid; posts FINAL_SETTLEMENT and TRANSPORT_CREDIT ledger entries | POOL_ACCOUNTANT |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CAMPAIGN_NOT_OPEN` | 409 |
| `ERR_BOOKING_NOT_CONFIRMED` | 409 |
| `ERR_TICKET_NOT_CREDITABLE` | 409 |
| `ERR_POOL_NOT_ACCRUING` | 409 |
| `ERR_PILE_NOT_FILLING` | 409 |
| `ERR_LAB_SAMPLE_REQUIRED` | 409 |
| `ERR_MEMBER_SUSPENDED` | 409 |
| `ERR_SLOT_OUTSIDE_WINDOW` | 422 |
| `ERR_WEIGH_WINDOW_CLOSED` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_SURVEY_BLACKOUT` | 409 |
| `ERR_PILE_CAPACITY_EXCEEDED` | 409 |
| `ERR_INVALID_WEIGHTS` | 422 |
| `ERR_TRASH_LIMIT_EXCEEDED` | 422 |
| `ERR_PILE_STATION_MISMATCH` | 422 |
| `ERR_SHIPPED_WEIGHT_MISMATCH` | 422 |
| `ERR_MEASURED_WEIGHT_INVALID` | 422 |
| `ERR_POOL_ACCRUAL_CAP_EXCEEDED` | 409 |
| `ERR_INSTALLMENT_PCT_INVALID` | 422 |
| `ERR_POOL_NO_SUGAR` | 422 |
| `ERR_REVERSAL_NOT_ALLOWED` | 409 |
