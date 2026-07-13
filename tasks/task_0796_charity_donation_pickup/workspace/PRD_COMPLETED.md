# Charity Donation-Pickup API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Charity Donation-Pickup platform, a scheduling and settlement system in the spirit of curbside donation programs such as GreenDrop or Salvation Army pickups. Donors stage household goods for collection; a fleet of trucks, each dedicated on any given day to a particular charity, runs routes that sweep up those goods. The platform must reconcile two very different economic outcomes on the same collection event: a **donation**, which produces a tax receipt and — when small enough — is free to the donor, and a **haul**, which is priced junk removal that bills the donor for the labor and disposal.

The system coordinates five kinds of actors around this workflow. Donors describe what they want collected and where; dispatchers plan the day's routes and slot requests onto trucks; drivers appraise items in the field, complete or abandon each stop, and assign every item to a disposal stream; partner administrators configure their charity and correct the accounting record; and a platform administrator provisions the network and controls the logical clock that governs every date-sensitive rule. Because a truck's capacity, a partner's year-to-date totals, and a route's remaining slots are all shared state that several actors touch, the platform enforces immediate consistency: every computed total is recomputed the instant an underlying fact changes, and concurrent edits to a route are guarded by optimistic version checks.

The remainder of this document defines the global API contract (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than donor self-registration must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. When either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The platform recognizes six roles, spelled exactly as follows:

- **`Anonymous`** — an unauthenticated caller. This role is an opaque identifier not tied to any persisted entity; it exists solely so that a prospective donor may self-register. The only operation it may invoke is donor registration.
- **`Donor`** — owns pickup requests, donation items, and recurring plans, and pays their own haul invoices. For this role, `X-User-ID` is the `id` of the acting `Donor`. Ownership checks compare a resource's owning donor to `X-User-ID`: for a pickup request or recurring plan, the resource's `donor_id` must equal `X-User-ID`; for a donation item, the `donor_id` of the item's parent pickup request must equal `X-User-ID`; for a haul invoice, the `donor_id` of the invoice's pickup request must equal `X-User-ID`. A mismatch is rejected with `ERR_UNAUTHORIZED`.
- **`Dispatcher`** — plans routes, schedules pickups, and materializes recurring pickups. `X-User-ID` for a dispatcher is an opaque operator identifier not compared to any entity's `id`.
- **`Driver`** — services pickups in the field: appraises items, completes pickups, and marks no-shows. `X-User-ID` for a driver is an opaque operator identifier not compared to any entity's `id`.
- **`PartnerAdmin`** — manages one charity partner's configuration and voids that partner's receipts. For this role, `X-User-ID` is the `id` of the acting `CharityPartner`; ownership checks compare the target resource's `partner_id` to `X-User-ID`, so a partner administrator may only void a receipt whose `partner_id` equals `X-User-ID` and may only reconfigure their own partner record.
- **`PlatformAdmin`** — provisions partners, vehicles, and donors, and controls the logical clock. `X-User-ID` for a platform administrator is an opaque operator identifier not compared to any entity's `id`.

Ownership enforcement (the checks described above for `Donor` and `PartnerAdmin`) applies to donor-owned writes — creating a pickup request, adding an item, cancelling a request, paying an invoice, creating a recurring plan and its pause/resume/cancel actions — and to a partner administrator voiding a receipt. Read (`GET`) operations are available to every authenticated role.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of records to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of records matching the filter before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties

Every entity in the system — charity partners, vehicles, routes, donors, recurring plans, pickup requests, donation items, route stops, donation receipts, and haul invoices — carries a standard set of server-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that begins at creation and increments by one on every mutation of the resource. It underpins the optimistic concurrency mechanism described in Section 2.7.

All ten entities in this system carry the full set above (all four fields). Timestamps that record domain events — such as a receipt's `issued_at` — are distinct from these audit fields and are described where the corresponding workflow is defined.

### 2.5. Nested Resource Retrieval and Referential Existence

Several paths address a child resource through its parent, and several request bodies carry foreign keys to other resources. Two ordered existence checks govern these.

First, for any path that carries one or more identifiers, the identifiers are validated left to right against live resources. The first identifier that does not resolve produces that resource's not-found error — `ERR_PARTNER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_PLAN_NOT_FOUND` as appropriate — and evaluation stops there before any deeper check runs.

Second, foreign keys supplied in a request body — such as `donor_id`, `partner_id`, `route_id`, `recurring_plan_id`, and `vehicle_id` — must resolve to live resources. This applies when creating a pickup request, creating a route, creating a recurring plan, and scheduling a pickup onto a route. A dangling body reference yields the corresponding not-found error listed above.

### 2.6. Monetary and Volumetric Precision

All monetary amounts are integer cents; all volumes are integer cubic feet; all weights are integer pounds. Wherever a calculation multiplies a value by a fractional factor — the fair-market condition factors of Section 3.6 and the diversion-credit cap of Section 3.6 — the intermediate result is rounded to whole cents using the round-half-up convention (a value exactly at the halfway point rounds up). The precise point at which rounding is applied within each formula is stated with that formula, because rounding each item before summing does not generally equal rounding the sum.

### 2.7. Optimistic Concurrency on Route Scheduling

Scheduling a pickup onto a route mutates shared route state — its reserved volume and stop counts — that a dispatcher must read before deciding whether a new stop fits. To prevent a dispatcher from acting on a stale capacity view, the scheduling operation requires the field `expected_route_version` in its request body, carrying the `version` of the target route that the dispatcher last observed. This field is mandatory for scheduling, not optional.

When the scheduling request is processed, `expected_route_version` is compared against the target route's current `version`. If another writer has added or removed a stop on that route since the dispatcher read it, the route's `version` (and its `reserved_volume_cf`) will have advanced, the submitted value will no longer match, and the schedule is rejected with `ERR_STALE_VERSION` (HTTP 412). An absent `expected_route_version` is treated as a non-matching value and is likewise rejected with `ERR_STALE_VERSION`, not with a field-validation error. This is the only endpoint that takes a version field; no other operation accepts or checks `expected_route_version`.

### 2.8. Derived-Field Reconciliation and Cascade Consistency

Many fields are computed rather than supplied, and the system recomputes each one immediately whenever an input to it changes, in the same operation that caused the change. A recomputation that alters a resource is a mutation: it refreshes that resource's `updated_at` and increments its `version`.

The derived fields and their reconciliation triggers are:

- A pickup request's `declared_volume_cf`, `is_free_donation`, and `estimated_haul_fee_cents` are recomputed every time an item is added to that request (Section 3.2).
- A route's `reserved_volume_cf` and `total_stop_count` are recomputed whenever one of its stops is created, cancelled, or serviced; its `serviced_stop_count` is recomputed when a stop is serviced (Section 3.3, Section 3.5).
- A charity partner's `ytd_donation_value_cents` is recomputed when one of its donation receipts is issued and when one is voided; its `diverted_weight_lbs` is recomputed when one of its pickups completes and when a receipt is voided (Section 3.8).

Because a single operation such as completing a pickup can mutate the pickup request, its route stop, its route, and its charity partner, every one of those cascade targets independently receives a refreshed `updated_at` and an incremented `version`.

### 2.9. The Logical Clock

The server keeps a logical clock that starts at `2026-03-01T00:00:00Z` and never falls back to wall-clock time. Every date-, year-, and expiry-sensitive rule — a recurring plan's next pickup date, a receipt's `issued_at`, and the calendar year used for a partner's year-to-date total — reads this clock. A platform administrator may advance the clock to a supplied instant; the operation carries a single field, `to_iso8601`, naming the new logical time.

### 2.10. Request Validation Order

When more than one condition could reject a request, checks are evaluated in a fixed priority order so that failures are reported deterministically. The global order is:

1. Authentication — the `X-User-Role` and `X-User-ID` headers are present and the role is recognized (`ERR_UNAUTHENTICATED`, 401). This applies to every endpoint except donor self-registration, which `Anonymous` may call.
2. Authorization by role — the role is permitted to invoke this endpoint (`ERR_UNAUTHORIZED`, 403).
3. Path existence — every identifier in the path resolves, left to right (the appropriate not-found error, 404).
4. Ownership — entity-backed ownership as defined in Section 2.1 (`ERR_UNAUTHORIZED`, 403).
5. Body reference existence — foreign keys in the body resolve (the appropriate not-found error, 404).
6. Transition legality — the target resource is in a state that admits the requested transition (`ERR_REQUEST_INVALID_STATE`, `ERR_ROUTE_INVALID_STATE`, `ERR_PLAN_INVALID_STATE`, `ERR_RECEIPT_NOT_VOIDABLE`, or `ERR_INVOICE_INVALID_STATE`, all 409).
7. Cross-entity state gate — a required state on a related resource (`ERR_ROUTE_NOT_OPEN`, `ERR_VEHICLE_OUT_OF_SERVICE`, or `ERR_PARTNER_SUSPENDED`, all 409).
8. through 16. — the business rules specific to the operation, in the order given in the relevant workflow subsection.
17. Field-level input validity — required fields present, enum values in range, numeric fields within their declared bounds, and window/slot end strictly after start (`ERR_INVALID_REQUEST`, 400). This is the lowest-priority check.

The business-rule band (priorities 8–16) is populated almost entirely by the scheduling operation and is enumerated in Section 3.4; the route-window rule at priority 8 governs route creation and is described in Section 3.3.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Network

The platform administrator stands up the shared infrastructure. A **charity partner** is created with its legal `name`, the `region_code` it serves (for example `CA-BAY` or `NY-METRO`), the `tax_id` printed on its donation receipts, and its `accepted_categories` — a non-empty subset of the item categories `FURNITURE`, `CLOTHING`, `ELECTRONICS`, `APPLIANCE`, and `HOUSEHOLD` that the partner is willing to receive as donations. A partner's `status` may be supplied and is otherwise `ACTIVE`; the only other value is `SUSPENDED`. A suspended partner cannot have a recurring plan resumed onto it — the resume action is the only point at which suspension is enforced, so a suspended partner is not otherwise blocked from receiving new pickup requests or from having its donations scheduled and completed. A partner's two rolling totals, `ytd_donation_value_cents` and `diverted_weight_lbs`, both begin at zero and are only ever moved by the reconciliations of Section 3.8. A partner administrator (or the platform administrator) may later revise a partner's `status` and/or its `accepted_categories`; each such edit increments the partner's `version`.

A **vehicle** is created with a human-readable `label`, a `capacity_cf` giving the maximum cubic feet it can carry on one route (which must be greater than zero), and a `home_depot_code` naming the depot it returns to. Its `status` may be supplied and defaults to `ACTIVE`; an `OUT_OF_SERVICE` vehicle cannot have a route opened onto it.

A **donor** registers with an `email` (recorded as supplied; the system does not enforce email uniqueness), a `full_name`, a default pickup `address`, and their `region_code`. Registration is the one operation open to an anonymous caller as well as to the platform administrator; a donor's `status` is set to `ACTIVE` at registration and has no other value.

### 3.2. Composing a Pickup Request and Its Item List

A donor opens a **pickup request** by naming the receiving charity through `partner_id`, identifying themselves through `donor_id`, and choosing two modes. The `pickup_mode` is either `ATTENDED`, meaning a crew enters the home, or `UNATTENDED`, meaning items are left on the porch. The `disposition` is either `DONATION`, which yields a tax receipt and is free below a volume cap, or `HAUL`, which is priced junk removal. The request also carries the pickup `address`. Two fields support the unattended flow and may be supplied now or later: `porch_photo_url`, a photo of the staged items, and `safety_attestation`, a boolean by which the donor attests the items are safely accessible (it defaults to `false`). A request may optionally carry a `recurring_plan_id`; this is populated only when the request was materialized by a recurring plan (Section 3.7) and is otherwise absent. A freshly created request is `REQUESTED`, its `declared_volume_cf` is zero, its `estimated_haul_fee_cents` is zero, and its `is_free_donation` reflects its disposition.

While the request is still `REQUESTED`, the donor builds its item list. Each **donation item** names its `category` (one of the five category values above), the `volume_cf` it occupies (which must be greater than zero), its `weight_lbs` (which must be zero or greater), the donor's `declared_value_cents` (zero or greater), and its `declared_condition` — one of `NEW`, `GOOD`, `FAIR`, or `POOR`. The item's appraisal fields — `appraised_value_cents`, `appraised_condition`, and `stream` — are set only later by the driver (Section 3.5) and are absent until then.

Adding an item triggers three immediate recomputations on the parent request. The request's `declared_volume_cf` becomes the sum of `volume_cf` over all of its items — every item is included, since items are not individually removable. The request's `is_free_donation` becomes true exactly when the disposition is `DONATION` and the declared volume is at most 50 cubic feet, and false otherwise. And the request's `estimated_haul_fee_cents` is recomputed as a forward-looking haul estimate: for a `HAUL` request it is the haul subtotal computed from the current `declared_volume_cf` with no diversion credit applied (because nothing has been appraised yet), and for a `DONATION` request it is zero. The exact haul subtotal formula is given in Section 3.6.

### 3.3. Routes, Service Windows, and Capacity

A dispatcher plans the collection day by creating a **route**, which binds a truck to a charity for a dated service window. A route names its `vehicle_id`, its `partner_id`, the `service_date` (a `YYYY-MM-DD` calendar date the route runs), and a half-open service window from `window_start` (inclusive) to `window_end` (exclusive, and required to be strictly later than `window_start`). A new route begins `PLANNED`. Its capacity-accounting fields — `reserved_volume_cf`, `total_stop_count`, and `serviced_stop_count` — all begin at zero and are only ever moved by stop reconciliation.

At creation, a route's window is checked against the truck's existing commitments: the new half-open window must not overlap any non-`CLOSED` route already booked on the same `vehicle_id` and `service_date`. Because the window is half-open, exact adjacency is permitted — a new route whose `window_start` equals a prior route's `window_end` does not overlap it. A genuine overlap is rejected with `ERR_ROUTE_WINDOW_CONFLICT`.

A route moves through a small lifecycle. A dispatcher opens a route, advancing it `PLANNED → OPEN`, but only while it is still `PLANNED` and only if the referenced vehicle is `ACTIVE`; opening a route onto an `OUT_OF_SERVICE` vehicle is refused with `ERR_VEHICLE_OUT_OF_SERVICE`, and opening a route that is not `PLANNED` is refused with `ERR_ROUTE_INVALID_STATE`. Only an `OPEN` route accepts new stops. A dispatcher later closes a route, advancing it `OPEN → CLOSED`, but only while it is `OPEN` and only once no stop on it remains `RESERVED` — that is, every stop has been either serviced or cancelled; closing an `OPEN` route that still has a `RESERVED` stop is refused with `ERR_ROUTE_INVALID_STATE`, and closing a route that is not `OPEN` is likewise refused with `ERR_ROUTE_INVALID_STATE`. `CLOSED` is terminal. Each of open and close increments the route's `version`.

Throughout a route's life the three counters are kept current. Its `reserved_volume_cf` is always the sum of the `reserved_volume_cf` snapshots of its stops that are currently `RESERVED` — stops that have moved to `SERVICED` or `CANCELLED` no longer contribute. Its `total_stop_count` is the number of its stops that are either `RESERVED` or `SERVICED` (cancelled stops are excluded). Its `serviced_stop_count` is the number of its stops that are `SERVICED`. Each of these is recomputed as part of the stop transition that changes an input to it.

### 3.4. Scheduling a Pickup onto a Route

Scheduling is the platform's most guarded operation and the point at which a request joins a truck's itinerary. A dispatcher schedules a `REQUESTED` pickup by supplying the target `route_id`, the on-site time slot from `slot_start` (inclusive) to `slot_end` (exclusive), and the `expected_route_version` described in Section 2.7. A successful schedule advances the request `REQUESTED → SCHEDULED` and, as its side effects, creates a **route stop** joining the route and the request, recomputes the route's `reserved_volume_cf` and `total_stop_count`, and increments the route's `version` by one. The created stop starts `RESERVED`, snapshots the request's current `declared_volume_cf` into its own `reserved_volume_cf`, and records the supplied slot. Each stop also carries a `sequence`, the 1-based ordinal of the stop within its route ordered by ascending `slot_start` and then by `created_at`.

The scheduling checks run in this order, each after the generic authentication, authorization, path-existence, and body-existence checks of Section 2.10:

1. The request must be `REQUESTED`; otherwise `ERR_REQUEST_INVALID_STATE`.
2. The target route must be `OPEN`; otherwise `ERR_ROUTE_NOT_OPEN`.
3. The request must have at least one donation item; a request with none is rejected with `ERR_NO_ITEMS`.
4. If the request's `pickup_mode` is `UNATTENDED`, it must have a non-null `porch_photo_url` and a `safety_attestation` of true; otherwise `ERR_PORCH_ATTESTATION_REQUIRED`.
5. If the request's `disposition` is `DONATION`, every one of its items must have a `category` that is contained in the partner's `accepted_categories`; any item outside that set yields `ERR_CATEGORY_NOT_ACCEPTED`.
6. If the request's `disposition` is `DONATION`, its `declared_volume_cf` must be at most 50 cubic feet; a larger donation is rejected with `ERR_DONATION_OVER_LIMIT`.
7. The requested slot must sit inside the route window and be well-formed: `slot_start` at or after the route's `window_start`, `slot_end` at or before the route's `window_end`, and `slot_end` strictly after `slot_start`; any violation yields `ERR_SLOT_OUTSIDE_WINDOW`.
8. The slot must not crowd another stop. Considering every `RESERVED` or `SERVICED` stop already on the route, expand each such stop's slot by a 15-minute travel buffer on each side; if the requested slot overlaps any so-expanded slot, the schedule is rejected with `ERR_STOP_SLOT_CONFLICT`. Equivalently, the gap between the requested slot and any adjacent existing stop must be at least 15 minutes.
9. The truck must have room: the route's current `reserved_volume_cf` plus the request's `declared_volume_cf` must not exceed the vehicle's `capacity_cf`; otherwise `ERR_ROUTE_CAPACITY_EXCEEDED`.
10. Finally, `expected_route_version` must equal the route's current `version`; a mismatch yields `ERR_STALE_VERSION`.

Field-level input validity (`ERR_INVALID_REQUEST`) remains the lowest-priority check, as in Section 2.10.

### 3.5. Servicing in the Field: Appraisal, Completion, and No-Show

Once a request is `SCHEDULED`, a driver works the stop; appraising an item whose parent request is not `SCHEDULED` is rejected with `ERR_REQUEST_INVALID_STATE`. Before completing, the driver may appraise any item on the request, correcting the record to reflect what was actually collected: an appraisal may set the item's `appraised_value_cents`, its `appraised_condition` (one of `NEW`, `GOOD`, `FAIR`, `POOR`), a corrected `weight_lbs`, and its `stream` — the diversion stream, one of `RECYCLE`, `REUSE`, or `LANDFILL`. Items sent to `RECYCLE` or `REUSE` count as diverted from landfill; `LANDFILL` items do not. Appraising an item does not change the request's `estimated_haul_fee_cents`, which is a pre-appraisal, forward-looking estimate.

Completing a pickup advances the request `SCHEDULED → COMPLETED` and requires the driver to supply the `measured_volume_cf` actually collected, which is stored on the request. Completion services the stop: the request's route stop moves to `SERVICED`, and the route's `reserved_volume_cf` (the stop leaves the reserved set) and `serviced_stop_count` are recomputed. Completion then forks on the request's disposition into two disjoint settlement paths:

- **When the disposition is `DONATION`:** the system issues a **donation receipt** in status `ISSUED`, recording the completed pickup through its `request_id`, stamping its `provisional_value_cents` and `final_value_cents` (both computed as in Section 3.6), copying the `partner_id` from the request into the receipt, setting its `issued_at` to the current logical clock, and minting a `receipt_number`. Issuance recomputes the partner's `ytd_donation_value_cents` and its `diverted_weight_lbs`. No haul invoice is created.
- **When the disposition is `HAUL`:** the system creates a **haul invoice** in status `INVOICED`, recording the billed pickup through its `request_id`, and stamping its `estimate_cents` (a snapshot of the request's `estimated_haul_fee_cents`), its `final_cents`, its `diversion_credit_cents`, and its `amount_due_cents` (all computed as in Section 3.6). Completion of a haul recomputes the partner's `diverted_weight_lbs`. No donation receipt is created.

Receipts may be listed and filtered by their `request_id` or `partner_id`, and haul invoices may be listed for a given `request_id`; each donation item likewise carries the `request_id` of the pickup it belongs to.

Alternatively, a driver may mark a scheduled pickup a **no-show** — for instance, an empty porch — advancing the request `SCHEDULED → NO_SHOW`. A no-show cancels the request's route stop (the stop moves to `CANCELLED`) and recomputes the route's `reserved_volume_cf` and `total_stop_count`. No receipt or invoice is produced.

A donor may cancel their own request. Cancelling a still-`REQUESTED` request advances it `REQUESTED → CANCELLED` with no route side effects, since it was never placed on a route. Cancelling a `SCHEDULED` request advances it `SCHEDULED → CANCELLED` and, because it had a stop, cancels that route stop (moving it to `CANCELLED`) and recomputes the route's `reserved_volume_cf` and `total_stop_count`. A request that is already terminal admits none of these transitions and is rejected with `ERR_REQUEST_INVALID_STATE`; the same error guards completing or no-showing a request that is not `SCHEDULED`.

### 3.6. Valuation and Pricing: Receipts and Invoices

Two calculation families settle a completed pickup.

**Tax-receipt value.** A donation's fair-market value derives from a per-condition factor: `NEW` is valued at 1.00 of the stated value, `GOOD` at 0.70, `FAIR` at 0.40, and `POOR` at 0.15. The value is computed item by item and summed with the rounding order pinned: for each item, multiply its value by the factor of its condition and round that product to whole cents using round-half-up; then add the rounded per-item results together. Rounding is applied to each item first and the whole-cent results are summed afterward — never sum first and round once. The receipt carries two such figures. Its `provisional_value_cents` is computed from every item's donor-declared inputs — `declared_value_cents` paired with `declared_condition` — and represents the request before appraisal. Its `final_value_cents`, set at issuance, is computed per item from the appraised inputs when the item has been appraised (its `appraised_value_cents` is present), using `appraised_value_cents` paired with `appraised_condition` (falling back to that item's `declared_condition` when no `appraised_condition` was recorded), and otherwise from that item's declared pair.

**Haul fee.** A haul's price is built from a subtotal and then reduced by a diversion credit. The subtotal is a flat base fee of 3,500 cents, plus a volume charge computed on a marginal, tiered schedule, plus — only when the request's `pickup_mode` is `ATTENDED` — a surcharge of 2,000 cents. The tiered volume charge over a volume of V cubic feet is: 40 cents for each of the first 100 cubic feet; 60 cents for each cubic foot above 100 up to and including 250 (that is, the next 150 cubic feet); and 80 cents for each cubic foot above 250. The diversion credit rewards items kept out of landfill: sum the `weight_lbs` of the request's items whose `stream` is `RECYCLE` or `REUSE`, multiply that diverted weight by 5 cents per pound, and cap the result at 30 percent of the subtotal, where the cap is computed as the subtotal times 0.30 rounded half-up to whole cents; the credit is the smaller of the per-pound amount and that cap. The amount due is the subtotal minus the credit, but never below zero.

The haul fee has two variants over the same schedule. The **estimate** variant is what feeds `estimated_haul_fee_cents` on each item add and is snapshotted into the invoice's `estimate_cents` at completion: it uses V equal to the request's `declared_volume_cf` and forces the diversion credit to zero, since nothing has been appraised. The **final** variant produces the invoice's `final_cents` (the subtotal before credit) and `amount_due_cents`: it uses V equal to the request's `measured_volume_cf` and computes the diversion credit from the appraised streams and weights of the request's items, recording that credit in `diversion_credit_cents`.

A haul invoice is settled by the donor, who pays it, advancing it `INVOICED → PAID`; paying an invoice that is not `INVOICED` is rejected with `ERR_INVOICE_INVALID_STATE`.

A donation receipt may be voided by the partner administrator who owns it, advancing it `ISSUED → VOIDED`; voiding a receipt that is not `ISSUED` is rejected with `ERR_RECEIPT_NOT_VOIDABLE`. Voiding drops the receipt out of the issued set and therefore recomputes the partner's `ytd_donation_value_cents` — debiting exactly the voided receipt's `final_value_cents` as compensation — and recomputes the partner's `diverted_weight_lbs` for the underlying pickup, as detailed in Section 3.8.

### 3.7. Recurring Plans

A donor may set up a **recurring plan** so that pickups are generated on a cadence rather than opened one at a time. A plan names the owning `donor_id`, the receiving `partner_id`, the `pickup_mode` and `default_disposition` to stamp onto each generated request, the pickup `address`, and a `frequency` — one of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`. The plan tracks a `next_pickup_date`: at creation it is set to the current logical-clock date advanced by one cadence step, and it advances by one further step each time the plan generates. A cadence step is 7 days for `WEEKLY`, 14 days for `BIWEEKLY`, and one calendar month for `MONTHLY`. A new plan begins `ACTIVE`.

A dispatcher materializes the next pickup by generating from an `ACTIVE` plan. Generation creates a new `REQUESTED` pickup request stamped from the plan — carrying the plan's `donor_id`, `partner_id`, `pickup_mode`, `address`, and the plan's `default_disposition` as the request's `disposition` — with the request's `recurring_plan_id` set to this plan; it then advances the plan's `next_pickup_date` by one cadence step. Generating from a plan that is not `ACTIVE` is refused with `ERR_PLAN_INVALID_STATE`.

The donor manages the plan's lifecycle, which is a cyclic active/paused machine with a terminal cancellation. Pausing an `ACTIVE` plan advances it `ACTIVE → PAUSED`; only `ACTIVE` plans may generate, so a paused plan produces nothing until resumed. Resuming advances a `PAUSED` plan `PAUSED → ACTIVE`, but only if the plan's charity partner is currently `ACTIVE`; resuming onto a `SUSPENDED` partner is refused with `ERR_PARTNER_SUSPENDED`. The plan may be cancelled from either the `ACTIVE` or the `PAUSED` state, advancing it to the terminal `CANCELLED`. Any lifecycle action attempted from a state that does not admit it is rejected with `ERR_PLAN_INVALID_STATE`.

### 3.8. Diversion and Year-to-Date Partner Accounting

Two rolling totals on each charity partner summarize its impact, and both are pure reconciliations recomputed from scratch whenever a triggering event occurs — never incremented blindly.

A partner's `ytd_donation_value_cents` is the sum of `final_value_cents` over that partner's donation receipts that are currently `ISSUED` and whose `issued_at` falls in the same calendar year as the current logical clock. It is recomputed when a receipt is issued at donation completion and when a receipt is voided; because a voided receipt leaves the `ISSUED` set, the recomputation naturally removes its contribution, which for a receipt issued in the current year debits exactly its `final_value_cents`.

A partner's `diverted_weight_lbs` is the sum of `weight_lbs` over all donation items that belong to that partner's `COMPLETED` pickups and whose `stream` is `RECYCLE` or `REUSE`. It is recomputed when one of the partner's pickups completes — for both donation and haul dispositions — and when a receipt is voided.

## 4. Endpoint Definitions

Operations that create a new resource — a partner, vehicle, route, donor, pickup request, donation item, route stop (via scheduling), recurring plan, or a plan-generated request — return `201 Created`. All other operations, including state transitions, appraisal edits, partner updates, and reads, return `200 OK`. Errors carry the status codes catalogued in Section 5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/partners` | Create a charity partner | PlatformAdmin |
| GET | `/partners/{id}` | Fetch a charity partner | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| PATCH | `/partners/{id}` | Update partner status and/or accepted categories | PartnerAdmin, PlatformAdmin |
| POST | `/vehicles` | Create a vehicle | PlatformAdmin |
| POST | `/routes` | Create a route on a vehicle for a partner and window | Dispatcher |
| GET | `/routes/{id}` | Fetch a route with computed reserved volume and stop counts | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| GET | `/routes` | List routes, filterable by vehicle_id, partner_id, status | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| POST | `/routes/{id}/open` | Open a route for scheduling | Dispatcher |
| POST | `/routes/{id}/close` | Close a route | Dispatcher |
| GET | `/routes/{id}/stops` | List a route's stops | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| POST | `/donors` | Register a donor | Anonymous, PlatformAdmin |
| GET | `/donors/{id}` | Fetch a donor | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| POST | `/pickup-requests` | Create a pickup request | Donor |
| GET | `/pickup-requests/{id}` | Fetch a pickup request with computed fields | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| GET | `/pickup-requests` | List pickup requests, filterable by donor_id, partner_id, recurring_plan_id, status | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| POST | `/pickup-requests/{id}/items` | Add a donation item to a requested pickup | Donor |
| GET | `/pickup-requests/{id}/items` | List a request's donation items | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| GET | `/pickup-requests/{id}/stops` | List route stops for a request | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| GET | `/pickup-requests/{id}/haul-invoices` | List haul invoices for a request | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| POST | `/pickup-requests/{id}/schedule` | Schedule a request onto an open route, creating a stop | Dispatcher |
| POST | `/pickup-requests/{id}/complete` | Complete a scheduled pickup; issue a receipt or haul invoice | Driver |
| POST | `/pickup-requests/{id}/no-show` | Mark a scheduled pickup a no-show | Driver |
| POST | `/pickup-requests/{id}/cancel` | Cancel a requested or scheduled pickup | Donor |
| PATCH | `/donation-items/{id}` | Driver appraisal of an item (value, condition, weight, stream) | Driver |
| GET | `/donation-receipts/{id}` | Fetch a donation receipt | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| GET | `/donation-receipts` | List donation receipts, filterable by request_id, partner_id, status | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| POST | `/donation-receipts/{id}/void` | Void an issued receipt; compensate partner totals | PartnerAdmin |
| POST | `/haul-invoices/{id}/pay` | Mark an invoice paid | Donor |
| POST | `/recurring-plans` | Create a recurring pickup plan | Donor |
| GET | `/recurring-plans/{id}` | Fetch a recurring plan | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| GET | `/recurring-plans` | List recurring plans, filterable by donor_id, partner_id, status | Donor, Dispatcher, Driver, PartnerAdmin, PlatformAdmin |
| POST | `/recurring-plans/{id}/pause` | Pause an active plan | Donor |
| POST | `/recurring-plans/{id}/resume` | Resume a paused plan | Donor |
| POST | `/recurring-plans/{id}/cancel` | Cancel a plan | Donor |
| POST | `/recurring-plans/{id}/generate` | Materialize the next pickup request from a plan | Dispatcher |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PARTNER_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_DONOR_NOT_FOUND` | 404 |
| `ERR_REQUEST_NOT_FOUND` | 404 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_RECEIPT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_REQUEST_INVALID_STATE` | 409 |
| `ERR_ROUTE_INVALID_STATE` | 409 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_RECEIPT_NOT_VOIDABLE` | 409 |
| `ERR_INVOICE_INVALID_STATE` | 409 |
| `ERR_ROUTE_NOT_OPEN` | 409 |
| `ERR_VEHICLE_OUT_OF_SERVICE` | 409 |
| `ERR_PARTNER_SUSPENDED` | 409 |
| `ERR_ROUTE_WINDOW_CONFLICT` | 409 |
| `ERR_NO_ITEMS` | 422 |
| `ERR_PORCH_ATTESTATION_REQUIRED` | 422 |
| `ERR_CATEGORY_NOT_ACCEPTED` | 422 |
| `ERR_DONATION_OVER_LIMIT` | 422 |
| `ERR_SLOT_OUTSIDE_WINDOW` | 422 |
| `ERR_STOP_SLOT_CONFLICT` | 409 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
