# Commuter Rail Fare API — Product Requirements Document

## 1. Introduction

The Commuter Rail Fare API is the back-office and onboard settlement engine for a multi-agency commuter railroad. It replaces a fragmented mix of paper passes, standalone ticket machines, and spreadsheet-based revenue reconciliation with a single system that prices every journey, issues and activates mobile tickets, arbitrates onboard inspections, and apportions each fare across the operating agencies whose track the passenger actually rode.

The domain is unusually dense with interacting money rules. A single fare is shaped by the zone pair travelled, whether the trip is peak or off-peak, whether the rider qualifies for a reduced fare, and how far a passenger later extends their journey when a conductor finds them beyond their ticketed zone. Around that pricing core sit several compliance and compensation workflows: fare-evasion citations that escalate for repeat offenders and can strip a rider of reduced-fare eligibility, refunds and exchanges that move money into a store-credit wallet, and service credits that compensate riders for delays. Each of these workflows mutates shared passenger state, so the system treats every such change as an atomic, versioned event with fully specified cascades.

This document specifies the complete external contract: the entities and their fields, the state machines that govern tickets, applications, citations, refunds, and credits, the exact calculation of every monetary amount, the ordered validation rules that guard each operation, and the role-based access model that separates riders (`Passenger`), onboard staff (`Conductor`), and back-office operators (`FareAdmin`).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply to every endpoint. Business-process detail lives in Section 3; the two sections are meant to be read together.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles: `Passenger`, `Conductor`, and `FareAdmin`.

- When `X-User-Role` is `Passenger`, `X-User-ID` is the `id` of the acting `Passenger` entity. Ownership checks on any resource that references a passenger compare that resource's passenger foreign key to `X-User-ID`: a rider may act only on their own tickets, applications, refund requests, and citations. When a passenger acts on a resource owned by a different passenger, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Conductor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`. Conductors perform onboard inspections, upgrades, and citations.
- When `X-User-Role` is `FareAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. FareAdmins own fare configuration, passenger registration, application and refund decisions, citation resolution, service disruptions, credits, and the logical clock.

The precise set of roles authorized for each endpoint is given in the Section 4 endpoint table; ownership narrows that further for passenger-owned resources as described above.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific endpoint states otherwise, every list is returned sorted by the resource's creation timestamp in ascending order. Each list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the total number of matching records before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` formatted as a UUID, with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC string with three fractional digits.

Resources that are mutable over their lifetime — `Passenger`, `ReducedFareApplication`, `Ticket`, `Citation`, `RefundRequest`, and `ServiceCredit` — additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by one on every mutation.

The remaining entities are immutable append-only records and therefore carry only `id` and `created_at`; they expose neither `updated_at` nor `version`. These are `FareProduct`, `Agency`, `Inspection`, `Upgrade`, and `ServiceDisruption`. An `Inspection` and an `Upgrade`, once written, are never modified; a `FareProduct` and an `Agency` are configuration rows fixed at creation; and a `ServiceDisruption` records a historical delay that is never edited.

### 2.5. State Propagation, Cascades, and Version Semantics

Many operations touch more than one entity in a single atomic request, and each secondary mutation is a full mutation of its own: it refreshes that entity's `updated_at` and increments its `version`. Whenever a ticket is activated, validated, refunded, exchanged, or upgraded, the ticket's `version` increments by one. Whenever a passenger's wallet balance, reduced-fare eligibility, or evasion count changes as a side effect of some other operation, the passenger's `version` increments by one. Whenever a citation transitions, the citation's `version` increments by one.

Several workflows chain these effects across entities. Issuing a citation increments the cited passenger's `evasion_count` and, when that count reaches the revocation threshold, revokes any approved reduced-fare eligibility on the same passenger in the same request. Dismissing a contested citation reverses the earlier `evasion_count` increment. Approving a refund drives the referenced ticket into its refunded state, zeroes that ticket's revenue allocations, and — for wallet refunds — credits the passenger. These cascades are described in full in the relevant Section 3 workflows; the governing principle here is that every one of them is applied atomically and every affected entity's `version` advances.

### 2.6. Existence Checks and Resource Resolution

Before any business rule runs, the system confirms that every resource referenced by the request — whether named in the path or in the body — exists. References are validated left to right in the order they appear. A missing passenger yields `ERR_PASSENGER_NOT_FOUND`; a missing fare product yields `ERR_FARE_PRODUCT_NOT_FOUND`; a missing ticket yields `ERR_TICKET_NOT_FOUND`; a missing reduced-fare application yields `ERR_APPLICATION_NOT_FOUND`; a missing inspection yields `ERR_INSPECTION_NOT_FOUND`; a missing citation yields `ERR_CITATION_NOT_FOUND`; a missing refund request yields `ERR_REFUND_REQUEST_NOT_FOUND`; a missing service disruption yields `ERR_DISRUPTION_NOT_FOUND`; and a missing service credit yields `ERR_SERVICE_CREDIT_NOT_FOUND`. All existence failures return HTTP 404. When an upgrade references a fare that has no configured product for the observed zone pair and ticket type, that too is an `ERR_FARE_PRODUCT_NOT_FOUND` condition.

### 2.7. Ordered Validation Precedence

When several checks guard one operation, they are evaluated in a fixed precedence so that the returned error is deterministic. The order is: (1) authentication of the request headers, then (2) role authorization, then (3) existence of every referenced resource, then (4) resource ownership for passenger-owned resources together with structural validity of the request body, then (5) the target resource's state eligibility for the requested transition, then (6) business-referential rules such as reduced-fare eligibility and inspection/ticket linkage, then (7) time-window rules such as activation deadlines and refund windows, then (8) remaining business constraints such as evasion or upgrade preconditions, then (9) fiscal sufficiency of the wallet, and finally (10) the optimistic-concurrency version check. Wherever a workflow in Section 3 lists multiple guards, they fire in this relative order.

Structural validity of a request body — required fields present, enum fields carrying a permitted value, and integers within their declared ranges — is enforced with `ERR_INVALID_REQUEST` (HTTP 422) on every write. Zone numbers on fare products and inspections must be integers from 1 through 6 inclusive, and an agency's served-zone list must be non-empty with each entry from 1 through 6 inclusive.

### 2.8. The Wallet Credit Ledger

Each passenger holds a store-credit balance in `wallet_credit_cents`, denominated in integer cents and never allowed to fall below zero. The balance rises when a wallet-destined refund is approved, when a service credit is issued, and when an exchange to a cheaper fare produces a positive difference. It falls when credit is applied toward a purchase or an exchange, and when an issued service credit is later voided. Conceptually, the balance always equals the sum of issued service credits plus approved wallet refunds plus exchange credits, minus the wallet amounts spent on tickets.

Any attempt to spend more wallet credit than the passenger currently holds is rejected with `ERR_INSUFFICIENT_WALLET` (HTTP 402). This guard applies both when purchasing a ticket and when exchanging one.

### 2.9. Monetary Precision and Rounding

All monetary amounts in this system are integer cents; there are no fractional cents in stored values or API payloads. Where a calculation multiplies by a percentage or a ratio, the specification names the exact rounding step. The reduced-fare discount is the only step that rounds half up; proration and percentage-tier steps floor (truncate toward zero) as their formulas state; and revenue apportionment floors each agency's raw share and then distributes the leftover cents deterministically so that the parts always sum to the whole. Each calculation in Section 3 states its own rounding behavior explicitly, and those statements govern.

### 2.10. Optimistic Concurrency Control

Submitting a reduced-fare application is guarded by optimistic concurrency on the applicant passenger. A create request for a reduced-fare application must carry `expected_passenger_version`, a non-optional field holding the `version` of the passenger the client last observed. If that value does not equal the passenger's current `version` at the moment the create is processed — because the passenger has since been mutated by a prior application that superseded an earlier submission, an approval, an evasion increment, or a wallet change — the create is rejected with `ERR_STALE_PASSENGER_VERSION` (HTTP 412). This prevents a client from creating an application against passenger state it has not seen. No other endpoint takes a version field; this is the only optimistic-concurrency-guarded write in the system.

### 2.11. Temporal Governance and the Logical Clock

Every time-dependent rule in this system reads a single logical clock rather than wall-clock time. At startup the clock reads 2026-03-01T00:00:00Z, which precedes every fixture date, and it never falls back to real time. A `FareAdmin` may advance the clock by supplying a target instant in the `to_iso8601` field. All deadline, expiry, eligibility, proration, and age computations described in Section 3 are evaluated against this logical clock.

## 3. Business Logic & Workflows

### 3.1. Fare Configuration and Revenue-Sharing Setup

Before any rider can transact, a `FareAdmin` seeds the system with configuration. A fare product is a single immutable pricing row for one combination of `origin_zone`, `destination_zone`, and `ticket_type`. It declares an off-peak `base_fare_cents` and a `peak_surcharge_cents` that applies only to peak travel, both non-negative integers, and an `apportionment_method` that tickets priced from it inherit. That method is either `ZONE_COUNT` or `DISTANCE`, and when omitted it defaults to `ZONE_COUNT`. A ticket type is either `SINGLE`, representing one journey, or `MONTHLY`, representing a calendar-month pass.

A `FareAdmin` also registers the operating agencies that share fare revenue. Each agency is created with a unique `code` and a `zones_served` array listing the integer zone numbers it operates. When rounding remainders must be distributed during revenue apportionment, agencies are ordered by their creation timestamp ascending as the deterministic tie-break, so the order in which agencies are created is significant.

Passengers are registered by a `FareAdmin` with an `email`, a `full_name`, and a `date_of_birth` in `YYYY-MM-DD` form. A newly registered passenger starts with no reduced-fare category, a zero wallet balance, and a zero evasion count. The passenger record also exposes the computed `reduced_fare_category`, `reduced_fare_valid_until`, `wallet_credit_cents`, and `evasion_count` fields, all of which evolve through the workflows below.

### 3.2. Reduced-Fare Eligibility

A rider who believes they qualify for a discounted fare submits a reduced-fare application naming their own `passenger_id`, the requested `category` — one of `SENIOR`, `STUDENT`, or `DISABILITY` — an opaque `proof_document_ref`, and a `proof_expires_at` instant describing when their submitted proof lapses. The submission also carries `expected_passenger_version` for the concurrency guard described in Section 2.10. A fresh application legitimately supersedes any earlier application by the same passenger that is still in `SUBMITTED` status: on create, that prior application moves to `SUPERSEDED` and the passenger's `version` advances. Because that advance would invalidate a second client's observed version, the stale-version check in Section 2.10 is what keeps concurrent creates deterministic, rejecting the losing create with `ERR_STALE_PASSENGER_VERSION`. An application begins life in `SUBMITTED`.

A `FareAdmin` reviews a submission. Approval is permitted only while the application is `SUBMITTED`; otherwise it is rejected with `ERR_INVALID_APPLICATION_STATE`. For a `SENIOR` application, the passenger's age computed against the logical clock must be at least 65 years; if the rider is younger than 65, approval fails with `ERR_SENIOR_AGE_NOT_MET`. On approval the application's `valid_until` is set to the earlier of the submitted `proof_expires_at` and a date exactly 365 days after the current clock instant. The approval then writes the granted `category` onto the passenger's `reduced_fare_category`, copies `valid_until` onto the passenger's `reduced_fare_valid_until`, and advances the passenger's `version`. Rejection, also permitted only from `SUBMITTED`, records the supplied `reason` in the application's `decision_reason` and leaves the passenger untouched.

Eligibility is not permanent. As described in Section 3.6, accumulating enough fare-evasion citations revokes an approved application, moving it to `REVOKED`, clearing the passenger's `reduced_fare_category` back to having none, and nulling `reduced_fare_valid_until`. The terminal states of an application are therefore `REJECTED`, `SUPERSEDED`, and `REVOKED`; `APPROVED` is an operative state that can still be revoked.

### 3.3. Purchasing a Ticket: Pricing and Revenue Apportionment

A rider buys a ticket by naming their own `passenger_id`, the `fare_product_id` to price from, and the `travel_period` for the trip, which is `PEAK` or `OFF_PEAK`. Two optional inputs shape the charge: `use_reduced_fare`, a flag requesting the discount, and `wallet_apply_cents`, the amount of store credit to spend, which defaults to zero. At purchase the ticket copies the product's `ticket_type`, `origin_zone`, `destination_zone`, and `apportionment_method`, and records the spent credit in `wallet_applied_cents`.

The discount is only granted when it is both requested and earned. If `use_reduced_fare` is requested, the passenger must currently hold a reduced-fare category other than none and a `reduced_fare_valid_until` that is at or after the current clock instant; otherwise the purchase is rejected with `ERR_REDUCED_FARE_NOT_ELIGIBLE`. When the request is valid the ticket's `reduced_fare_applied` flag is set true and the discount is taken; otherwise the flag is false.

The charged amount, stored in `purchase_price_cents`, is computed as follows. Start with a subtotal equal to the product's base fare, adding the peak surcharge only when the travel period is peak. If the reduced fare applies, compute a discount equal to the subtotal multiplied by fifty percent, rounded half up, and subtract that discount from the subtotal; if it does not apply, the running price is simply the subtotal. Finally, cap the result at the fare ceiling of 5000 cents, taking the smaller of the running price and that ceiling as the purchase price. The half-up rounding applies only to the discount step.

When wallet credit is applied, the amount requested in `wallet_apply_cents` must not exceed the passenger's current balance, or the purchase fails with `ERR_INSUFFICIENT_WALLET`; on success the balance is reduced by that amount and the passenger's `version` advances.

Every non-refunded ticket carries a `revenue_allocations` array of per-agency shares, each entry pairing an `agency_id` and `agency_code` with an `amount_cents`, whose sum equals the purchase price. The split is computed by first forming the ticket's zone span — every integer zone from the smaller of origin and destination through the larger, inclusive. Each agency's weight is the set of its served zones that fall within that span: under `ZONE_COUNT` the weight is the count of those shared zones, and under `DISTANCE` the weight is the sum of their zone-mile values, where zone 1 is 10 miles, zone 2 is 20, zone 3 is 30, zone 4 is 40, zone 5 is 50, and zone 6 is 60. Only agencies with a positive weight participate. Each participating agency's raw share is the total purchase price multiplied by its weight and divided by the sum of all participating weights, computed as an exact ratio and then floored to whole cents. The cents left over after flooring — the total minus the sum of the floors — are handed out one cent at a time to agencies ordered by weight descending, breaking ties by agency creation timestamp ascending, until no leftover remains. The resulting allocation sums exactly to the purchase price.

### 3.4. Ticket Activation, Validation, and Exchange

A ticket's lifecycle is tracked in its `status` field, and list endpoints across the system accept a `status` filter to narrow results to a given lifecycle state. A purchased ticket begins in `PURCHASED` and branches into one of three fates: it can be activated for use, refunded, or exchanged. From `PURCHASED` a rider may activate the ticket, provided the current clock is no later than 90 days after the ticket's creation; activating after that window closes fails with `ERR_TICKET_ACTIVATION_EXPIRED`. Attempting to activate a ticket that is not in `PURCHASED` fails with `ERR_INVALID_TICKET_STATE`. Activation stamps `activated_at` with the current instant and computes `expires_at`: for a `SINGLE` ticket, 90 minutes after activation; for a `MONTHLY` ticket, the first instant of the calendar month following activation. For a monthly pass, activation is additionally blocked when the passenger already holds another activated monthly ticket for the same origin-destination zone pair whose validity month overlaps the one being activated, in which case the request fails with `ERR_PASS_PERIOD_OVERLAP`. Activation moves the ticket to `ACTIVATED` and advances its `version`.

Scan validation consumes a single-journey ticket. It is permitted only from `ACTIVATED`, only for a `SINGLE` ticket, and only while the current clock is at or before the ticket's `expires_at`; a validation attempted after expiry fails with `ERR_TICKET_EXPIRED`, and a validation on a ticket in the wrong state fails with `ERR_INVALID_TICKET_STATE`. A successful validation moves the ticket to the terminal `VALIDATED` state and advances its `version`. Either the ticket's owning passenger or a conductor may perform validation.

From `PURCHASED` a rider may instead exchange a ticket for a different fare product, supplying the `new_fare_product_id` and a `travel_period`, and optionally `wallet_apply_cents`. Exchange is permitted only from `PURCHASED`; otherwise it fails with `ERR_INVALID_TICKET_STATE`. The old ticket moves to the terminal `EXCHANGED` state and its revenue allocations are zeroed to a sum of zero. A brand-new ticket is created in `PURCHASED`, priced by the same purchase-price calculation and given its own revenue allocations. When the old ticket's purchase price exceeded the new ticket's purchase price, the positive difference is added to the passenger's wallet balance and the passenger's `version` advances. The exchange advances the old ticket's `version` as well.

### 3.5. Onboard Inspection and Fare Upgrades

A conductor inspects a rider onboard by recording the inspected `passenger_id`, the presented `ticket_id` (which is null when the rider presents no ticket), and the `observed_destination_zone` the rider is actually travelling to. The inspection is an append-only record whose `result` and `fare_shortfall_cents` are computed at creation. The result is `VALID` when the presented ticket genuinely covers the observed travel; `UPGRADE_REQUIRED` when a valid ticket is presented but the observed destination zone lies beyond the ticket's destination zone; and `EVASION` when no ticket is presented or the presented ticket is expired or otherwise not valid for the travel. For an evasion result the shortfall is fixed at the evasion fare estimate of 1000 cents. For an upgrade-required result the shortfall is the additional fare needed to reach the observed zone — the amount by which the full fare of the observed-zone product exceeds the ticket's purchase price, floored at zero. For a valid result the shortfall is zero.

When an inspection returns `UPGRADE_REQUIRED`, a conductor collects an onboard upgrade by referencing the `inspection_id` and the `ticket_id` being upgraded. The referenced inspection must have result `UPGRADE_REQUIRED`, or the request fails with `ERR_UPGRADE_NOT_REQUIRED`; and the supplied ticket must be the same one the inspection recorded, or it fails with `ERR_UPGRADE_TICKET_MISMATCH`. The upgrade records the ticket's prior destination as `from_zone` and the inspection's observed zone as `to_zone`, then overwrites the ticket's `destination_zone` to that observed zone and advances the ticket's `version`. The `upgrade_fare_cents` collected is computed by pricing the product for the ticket's origin zone, the observed destination zone, and the ticket's own ticket type: take that product's base fare, add its peak surcharge only when the ticket's travel period is peak, subtract the ticket's existing purchase price, floor the result at zero, and then add the flat onboard surcharge of 200 cents.

### 3.6. Fare Evasion, Citations, and the Revocation Cascade

An evasion inspection can escalate into a citation. A conductor issues a citation by referencing the `inspection_id` and the cited `passenger_id`. The inspection must have result `EVASION`, or issuance fails with `ERR_NO_EVASION_FOUND`, and the cited passenger must match the inspection's passenger. Issuance is the first hop of a three-part cascade. First, the penalty is computed using the passenger's evasion count as it stands before this citation: a repeat multiplier of 2 applies when that prior count is at least 2, and a multiplier of 1 applies otherwise, so the `base_penalty_cents` is the base evasion penalty of 5000 cents times that multiplier. The `total_penalty_cents` is that base penalty plus the `fare_shortfall_cents` copied from the inspection. Second, the passenger's `evasion_count` is incremented by one and their `version` advances. Third, if that increment brings the evasion count to at least the revocation threshold of 3 and the passenger holds an approved reduced-fare application, that application is moved to `REVOKED`, the passenger's reduced-fare category is cleared, and `reduced_fare_valid_until` is nulled — all within the same request. A citation begins in `ISSUED`.

A cited rider has two paths. They may pay the citation, permitted while it is `ISSUED` or `UPHELD`, moving it to the terminal `PAID` state and advancing its `version`. Or they may contest it, permitted only while it is `ISSUED`, which records the supplied `grounds` in the citation's `contest_grounds`, moves it to `CONTESTED`, and advances its `version`. An attempt to pay or contest from a state that does not permit the transition fails with `ERR_INVALID_CITATION_STATE`.

A `FareAdmin` resolves a contested citation by supplying a `decision`. Resolution is permitted only from `CONTESTED`. When the decision upholds the citation, the citation's `resolution_decision` is set to `UPHELD`, it moves to `UPHELD`, and its `version` advances; from there the rider may still pay it. When the decision dismisses the citation, the `resolution_decision` is set to `DISMISSED`, the citation moves to the terminal `DISMISSED` state, and — this is the divergent branch — the passenger's `evasion_count` is decremented by one as a compensating reversal, advancing the passenger's `version`. Only dismissal reverses the evasion count; upholding does not. The terminal states of a citation are `PAID` and `DISMISSED`.

### 3.7. Refunds

A rider requests a refund against a ticket by naming the `ticket_id`, a free-text `reason`, and a `refund_destination` that is either `WALLET` for store credit or `ORIGINAL` for the original tender. A refund may be requested only while the ticket is `PURCHASED` or `ACTIVATED`, and an activated ticket is refundable only when it is a monthly pass; a ticket that is terminal, or an activated single-journey ticket, is not refundable and the request fails with `ERR_TICKET_NOT_REFUNDABLE`. The request must also fall within 60 days of the ticket's creation, or it fails with `ERR_REFUND_WINDOW_ELAPSED`. On a valid request the `refund_amount_cents` is computed and the request is recorded in `REQUESTED`.

The refund amount has two variants selected by the ticket's state and type. For a purchased, unactivated ticket the full variant applies: the refund is the ticket's purchase price minus a flat refund fee of 200 cents, floored at zero, ignoring dates. For an activated monthly ticket the prorated variant applies: let the total days be the number of days in the calendar month of activation; let the used days be the whole number of days elapsed from the start of the activation day to the current clock instant, counted inclusively (that is, the floor of the elapsed days plus one); let the remaining days be the total days minus the used days, floored at zero; compute a gross refund equal to the purchase price multiplied by remaining days and divided by total days, floored to whole cents; and take the refund as that gross minus the 200-cent fee, floored at zero.

A `FareAdmin` decides the request. Approval is permitted only while the request is `REQUESTED` and the ticket is still `PURCHASED` or `ACTIVATED`; a decision on a request that is not `REQUESTED` fails with `ERR_INVALID_REFUND_STATE`. Approval drives the ticket into the terminal `REFUNDED` state, writes the computed amount onto the ticket's `refund_amount_cents`, zeroes every entry of the ticket's `revenue_allocations` so their sum becomes zero, and advances the ticket's `version`. When the destination is `WALLET`, the refund amount is added to the passenger's wallet balance and the passenger's `version` advances; when it is `ORIGINAL`, no wallet change occurs. Denial, permitted only from `REQUESTED`, records the supplied `reason` in the request's `decision_reason` and moves it to the terminal `DENIED` state. The terminal states of a refund request are therefore `APPROVED` and `DENIED`.

### 3.8. Service Disruptions and Compensation Credits

A `FareAdmin` records a service disruption on a line by supplying a `line_code`, a `scheduled_departure`, an `actual_departure` that must be at or after the scheduled departure, and an affected service window bounded by an inclusive `window_start` and an inclusive `window_end` that must be at or after the window start. The disruption computes `delay_minutes` as the whole number of minutes between scheduled and actual departure — the floor of the elapsed seconds divided by sixty — and a `severity` derived from it: `MINOR` for a delay under 30 minutes, `MAJOR` for a delay from 30 up to but not including 120 minutes, and `SEVERE` for a delay of 120 minutes or more. A new disruption's window on a given line must be separated by at least the 15-minute buffer from any existing disruption window on that same line; a window that falls within that buffer of an existing one is rejected with `ERR_DISRUPTION_WINDOW_CONFLICT`.

Against a recorded disruption, a `FareAdmin` issues a service credit for an affected ticket by referencing the `disruption_id` and the `ticket_id`. The disruption's delay must be at least 30 minutes, or issuance fails with `ERR_DELAY_BELOW_THRESHOLD`, and the ticket must be in `PURCHASED`, `ACTIVATED`, or `VALIDATED`. The credit copies the ticket's `passenger_id` onto the record and sets `credit_amount_cents` on a tiered scale over the ticket's purchase price: for a delay of at least 30 but under 60 minutes, twenty-five percent of the purchase price floored to whole cents; for a delay of at least 60 but under 120 minutes, fifty percent floored to whole cents; and for a delay of 120 minutes or more, the full purchase price. Issuing the credit adds its amount to the passenger's wallet balance and advances the passenger's `version`; the credit is recorded in `ISSUED`.

A `FareAdmin` may later void an issued credit by supplying a `reason`. Voiding is permitted only while the credit is `ISSUED`; otherwise it fails with `ERR_INVALID_CREDIT_STATE`. The void records the `void_reason`, moves the credit to the terminal `VOIDED` state, and subtracts the credit amount back out of the passenger's wallet balance as a compensating reversal, advancing the passenger's `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, drive a state transition, or set the clock return `200 OK`. The complete request and response shape for each endpoint is reconstructed from the workflow narratives in Section 3; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | FareAdmin |
| POST | `/fare-products` | Create a fare-product pricing row | FareAdmin |
| POST | `/agencies` | Create a revenue-sharing agency | FareAdmin |
| POST | `/passengers` | Register a passenger | FareAdmin |
| GET | `/passengers/{id}` | Fetch a passenger | FareAdmin, Passenger, Conductor |
| POST | `/reduced-fare-applications` | Submit a reduced-fare application | Passenger |
| GET | `/reduced-fare-applications/{id}` | Fetch a reduced-fare application | FareAdmin, Passenger |
| GET | `/reduced-fare-applications` | List reduced-fare applications | FareAdmin, Passenger |
| POST | `/reduced-fare-applications/{id}/approve` | Approve an application | FareAdmin |
| POST | `/reduced-fare-applications/{id}/reject` | Reject an application | FareAdmin |
| POST | `/tickets` | Purchase a ticket | Passenger |
| GET | `/tickets/{id}` | Fetch a ticket | FareAdmin, Passenger, Conductor |
| GET | `/tickets` | List tickets | FareAdmin, Passenger, Conductor |
| POST | `/tickets/{id}/activate` | Activate a ticket | Passenger |
| POST | `/tickets/{id}/validate` | Scan-validate a single ticket | Passenger, Conductor |
| POST | `/tickets/{id}/exchange` | Exchange an unactivated ticket | Passenger |
| POST | `/inspections` | Record an onboard inspection | Conductor |
| GET | `/inspections/{id}` | Fetch an inspection | FareAdmin, Conductor |
| GET | `/inspections` | List inspections | FareAdmin, Conductor |
| POST | `/upgrades` | Collect an onboard upgrade | Conductor |
| GET | `/upgrades/{id}` | Fetch an upgrade | FareAdmin, Conductor, Passenger |
| GET | `/upgrades` | List upgrades | FareAdmin, Conductor |
| POST | `/citations` | Issue a fare-evasion citation | Conductor |
| GET | `/citations/{id}` | Fetch a citation | FareAdmin, Conductor, Passenger |
| GET | `/citations` | List citations | FareAdmin, Conductor, Passenger |
| POST | `/citations/{id}/pay` | Pay a citation | Passenger |
| POST | `/citations/{id}/contest` | Contest a citation | Passenger |
| POST | `/citations/{id}/resolve` | Resolve a contested citation | FareAdmin |
| POST | `/refund-requests` | Request a refund | Passenger |
| GET | `/refund-requests/{id}` | Fetch a refund request | FareAdmin, Passenger |
| GET | `/refund-requests` | List refund requests | FareAdmin, Passenger |
| POST | `/refund-requests/{id}/approve` | Approve a refund | FareAdmin |
| POST | `/refund-requests/{id}/deny` | Deny a refund | FareAdmin |
| POST | `/service-disruptions` | Record a service disruption | FareAdmin |
| POST | `/service-credits` | Issue a service credit | FareAdmin |
| GET | `/service-credits/{id}` | Fetch a service credit | FareAdmin, Passenger |
| GET | `/service-credits` | List service credits | FareAdmin, Passenger |
| POST | `/service-credits/{id}/void` | Void an issued service credit | FareAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_PASSENGER_NOT_FOUND` | 404 |
| `ERR_FARE_PRODUCT_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_CITATION_NOT_FOUND` | 404 |
| `ERR_REFUND_REQUEST_NOT_FOUND` | 404 |
| `ERR_DISRUPTION_NOT_FOUND` | 404 |
| `ERR_SERVICE_CREDIT_NOT_FOUND` | 404 |
| `ERR_INVALID_TICKET_STATE` | 409 |
| `ERR_INVALID_CITATION_STATE` | 409 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_INVALID_REFUND_STATE` | 409 |
| `ERR_INVALID_CREDIT_STATE` | 409 |
| `ERR_TICKET_NOT_REFUNDABLE` | 409 |
| `ERR_REDUCED_FARE_NOT_ELIGIBLE` | 422 |
| `ERR_UPGRADE_TICKET_MISMATCH` | 409 |
| `ERR_TICKET_ACTIVATION_EXPIRED` | 409 |
| `ERR_TICKET_EXPIRED` | 409 |
| `ERR_REFUND_WINDOW_ELAPSED` | 409 |
| `ERR_NO_EVASION_FOUND` | 409 |
| `ERR_UPGRADE_NOT_REQUIRED` | 409 |
| `ERR_SENIOR_AGE_NOT_MET` | 422 |
| `ERR_PASS_PERIOD_OVERLAP` | 409 |
| `ERR_DISRUPTION_WINDOW_CONFLICT` | 409 |
| `ERR_DELAY_BELOW_THRESHOLD` | 422 |
| `ERR_INSUFFICIENT_WALLET` | 402 |
| `ERR_STALE_PASSENGER_VERSION` | 412 |
