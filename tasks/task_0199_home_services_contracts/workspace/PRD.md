# Home Services Contracts API — Product Requirements Document

## 1. Introduction

Residential HVAC and pest-control providers sell their customers more than a one-off repair: they sell an ongoing relationship. A homeowner enrolls in an annual membership, expects a fixed number of seasonal tune-up visits, and counts on priority response when something fails in the middle of a heat wave. Behind that promise sits a tangle of moving parts — dispatching the right certified technician to the right region, tracking refrigerant grams on every air-conditioning unit to stay inside EPA recovery rules, pricing parts at the member's negotiated discount, adjudicating warranty claims, and rolling the whole membership over into a new term once a year. The Home Services Contracts API is the system of record for that relationship.

This API governs the full lifecycle of a service agreement, from the moment a plan template is defined and a customer is enrolled, through the seasonal rhythm of booking, dispatching, and completing visits, down to the gram-level history of refrigerant moved on each piece of equipment. It is built around a small set of peer entities — service plans, customers, sites, memberships, equipment, technicians, service visits, refrigerant logs, part usages, warranty claims, and renewal offers — that reference one another by identifier rather than by deep ownership nesting. Time is a first-class concern: membership terms run on a 365-day clock, priority visits carry response-time service-level agreements, and renewal offers expire on a fixed instant. To make these temporal behaviors testable, the system exposes an administrative logical clock that can be set or advanced, firing renewal automation as it crosses offer expiry instants.

The sections that follow define the global contracts every endpoint obeys (Section 2), the domain workflows and the business rules woven through them (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5). All resources are mounted under the `/home-services` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they act. The system recognizes exactly four roles: `ContractAdmin`, `Dispatcher`, `Technician`, and `Customer`. A request that omits either header, or that carries an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation (per the endpoint catalogue in Section 4 and the workflow narratives in Section 3) is rejected with `ERR_UNAUTHORIZED`.

The four roles divide responsibility along business lines. A `ContractAdmin` owns the catalogue and the contract spine: it creates and retires service plans; creates customers, sites, equipment, and technicians; activates, suspends, reinstates, and cancels memberships; creates renewal offers; decommissions equipment; adjudicates warranty claims through review, approval, denial, and settlement; and drives the administrative test clock. A `Dispatcher` owns the scheduling and routing of visits — booking, rescheduling, dispatching, recalling, cancelling, and marking no-shows. A `Technician` owns on-site execution: departing toward, arriving at, and completing visits, and recording refrigerant moves, parts consumed, and warranty findings while on site. A `Customer` is the member, and may read its own records, cancel its own membership, and accept or decline its own renewal offers.

Two of these roles are entity-backed and two are opaque. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's `technician_id` to `X-User-ID` — a technician may only depart, arrive at, complete, or post refrigerant and parts against a `ServiceVisit` whose `technician_id` equals their own `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's owning `customer_id` chain to `X-User-ID`. A customer reading or cancelling a membership, reading a site or visit, or accepting/declining a renewal offer must own the underlying customer record; when a `Customer` acts on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `ContractAdmin` or `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single response returns; it defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter is the count of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list-based response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count` (the total number of matching resources before the page window is applied), and `has_more` (true when more resources remain beyond the current page).

### 2.4. Common Resource Properties and the Two Resource Tiers

Most resources are first-class, audit-tracked records. A first-class resource carries a system-minted `id` formatted as a UUID with no type prefix, a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording when it was created, an `updated_at` timestamp recording when it was last modified, and a `version` integer that starts at 1 and increments by exactly one on every mutation that changes the resource. The first-class resources are `ServicePlan`, `Customer`, `Site`, `Membership`, `Equipment`, `Technician`, `ServiceVisit`, `WarrantyClaim`, and `RenewalOffer`.

Two resources are append-only ledger entries rather than mutable records: `RefrigerantLog` and `PartUsage`. These carry only an `id` (UUID) and a `created_at` timestamp; they have neither an `updated_at` field nor a `version` field, because they are never modified after they are written. Their posting does, however, mutate the first-class resources they touch — a refrigerant log bumps the affected equipment's `version`, and a part usage debits the customer ledger.

### 2.5. Hierarchical Consistency, Cascades, and Reverse-Reachability Reads

Several operations mutate more than one resource at once. When a parent membership is suspended or cancelled, the system cascades down into the membership's open visits, and when a warranty claim is denied or settled it reaches across to the equipment and the customer ledger respectively. Every such cascade is spelled out in the workflow narratives of Section 3; the governing rule here is that whenever the server changes a first-class resource as part of a cascade, that resource's `updated_at` is refreshed and its `version` is incremented by one, exactly as if it had been mutated directly. The lone deliberate exception is a membership's `visits_consumed` counter: it is derived on read from the membership's completed visits within the current term window and is therefore never written back to the membership row, so completing a visit does not itself bump the owning membership's `version`.

Many resources are reachable in reverse through sub-resource list endpoints — equipment at a site, visits and renewal offers under a membership, refrigerant logs and part usages under a visit. For any path that carries more than one resource identifier, the server validates each identifier left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing resource, before evaluating any deeper segment or applying business rules.

### 2.6. Monetary and Mass Precision

All monetary amounts in this system — membership fees, extra-visit fees, part charges, claimed and approved amounts, and the running customer balance — are stored as integer cents, and no fractional cent ever arises from a calculation; amounts that involve a discount are rounded to whole cents using the round-half-up convention before they are recorded. Refrigerant quantities are stored as integer grams. Service-level latency is the only quantity measured in fractional units, computed in hours as a floating-point value for the purpose of the SLA comparison described in Section 3.

### 2.7. The Customer Ledger Principle

Each `Customer` carries a running `billing_balance_cents` that is the single source of truth for what the customer owes. It begins at 0 and is never set directly by a client. Instead, it moves only through the side effects of business events: activating a membership or accepting a renewal accrues the annual fee; completing an out-of-allowance or priority visit accrues the extra-visit fee; posting a part accrues the discounted part charge; and settling an approved warranty claim credits the balance back down. Every one of these movements is described in the workflow that triggers it, and each is an integer-cent debit or credit applied immediately. The system treats a settled warranty claim as a compensating credit: a claim that travels from submission through to settlement with an authorized amount moves the ledger by exactly the negative of that authorized amount and nothing more, while a denied claim moves the ledger by zero.

### 2.8. Optimistic Concurrency Control on Membership-Anchored Creates

Two create operations are guarded against acting on a stale view of their parent membership, because that membership's state may have advanced (through a suspend, a cancel, or a competing offer creation) since the client last read it.

Booking a service visit must carry `expected_membership_version`, a non-optional field that holds the `version` of the target `Membership` the client last observed. If that value does not match the membership's current `version` at the time the create is processed, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. This prevents a client from drawing a visit against a membership view that no longer reflects the membership's allowance or active state — for example, after a suspend has already cascade-cancelled the membership's visits.

Creating a renewal offer likewise must carry `expected_membership_version` holding the client's last observed `version` of the target `Membership`. If it does not match the membership's current `version`, the create is rejected with `ERR_STALE_VERSION` and HTTP status 412, preventing a second offer from being drawn against a membership another offer creation has already advanced into the `RENEWAL_PENDING` state.

No other endpoint takes a version field; only these two membership-anchored creates participate in optimistic concurrency control.

### 2.9. Validation Ordering

When several checks guard a single operation, they are evaluated in a fixed precedence so that the most fundamental failure surfaces first. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then — for a `Customer` acting on its own scoped resources — resource ownership (`ERR_NOT_RESOURCE_OWNER`). Next the system resolves every identifier: each path id and each foreign key referenced in the body must point to an existing resource, validated left to right, failing with `ERR_NOT_FOUND` at the first that does not resolve. Only then is the request body itself checked for being present, JSON-parseable, and complete with required fields of the correct types and valid enum values (`ERR_INVALID_REQUEST`). After these structural gates pass, the operation's domain-specific business rules apply, and where a state transition is involved the system confirms the target resource currently sits in a state from which that transition is defined, rejecting otherwise with `ERR_INVALID_STATE`. The remaining business rules — referential, safety, temporal, fiscal, and the stale-version guard — are described alongside the workflows they protect in Section 3. A generic business-rule violation that no more specific code covers falls back to `ERR_VALIDATION`; in practice every rule in this specification carries its own dedicated code, so this fallback is reserved rather than routinely emitted.

## 3. Business Logic & Workflows

### 3.1. Service Plans and the Catalogue

The catalogue begins with the **service plan**, a reusable template a `ContractAdmin` defines once and enrolls many customers against. A plan declares its `tier` — one of `BASIC`, `PLUS`, or `PREMIUM` — and the `trade` it covers, either `HVAC` or `PEST`. Its commercial terms are the `annual_fee_cents` billed once per term year (a non-negative integer), the `included_visits_per_year` seasonal visits folded into that fee (a non-negative integer), and the `extra_visit_fee_cents` charged whenever a visit beyond the included count is consumed (a non-negative integer). Two further terms shape service quality and pricing: `sla_response_hours`, the maximum number of hours a priority visit may wait between request and scheduled arrival window, which must be at least 1; and `parts_discount_pct`, a fraction between 0 and 1 inclusive that discounts the list price of parts for members on the plan. A plan also stamps a default onto memberships through `auto_renew_default`, a boolean that defaults to true when omitted at creation.

Every plan carries an `active` flag, a system-managed boolean that starts true. When a `ContractAdmin` retires a plan, the system sets `active` to false so the plan can no longer accept new memberships; memberships already enrolled on the plan keep their current term untouched. A plan must be active for a membership to be activated against it.

### 3.2. Customers, Sites, and Enrollment

A `ContractAdmin` registers a **customer** with a `full_name` and an `email`. The email must be non-empty and unique among customers. Each customer also exposes the computed `billing_balance_cents` described in Section 2.7, returned whenever the customer is fetched.

A **site** is a physical service address belonging to a customer. It is created with the owning `customer_id`, an `address`, a `region_code` that drives routing (a non-empty string such as `NORTH`, `SOUTH`, `EAST`, or `WEST`), and optional `access_notes` carrying gate codes or entry instructions, which default to an empty string when omitted. Sites can be listed and filtered by `customer_id` and `region_code`.

A **membership** ties a customer, a site, and a plan together for a term. It is created with the member's `customer_id`, the covered `site_id`, and the enrolled `plan_id`. At creation the membership's `auto_renew` flag is taken from the plan's `auto_renew_default` unless the request supplies its own `auto_renew` value, and the membership opens in `PENDING_ACTIVATION` status. A new membership is only well-formed when the referenced site actually belongs to the named customer: if the site's `customer_id` does not equal the membership's `customer_id`, the create is rejected with `ERR_SITE_OWNER_MISMATCH`. A membership's `status` moves through `PENDING_ACTIVATION`, `ACTIVE`, `RENEWAL_PENDING`, `SUSPENDED`, `LAPSED`, and `CANCELLED`. It exposes the current term window through `term_start` and `term_end`, the per-term `visits_consumed` count, and `term_index`, the number of completed renewal cycles. Memberships are listable and filterable by `customer_id`, `site_id`, `plan_id`, and `status`.

### 3.3. The Membership Term Lifecycle

A `ContractAdmin` activates a `PENDING_ACTIVATION` membership to begin its first term. Activation is permitted only when the membership is in `PENDING_ACTIVATION` and its referenced plan is currently active; an attempt against a non-pending membership is rejected with `ERR_INVALID_STATE`. On a successful `PENDING_ACTIVATION → ACTIVE` transition the system sets `term_start` to the current clock instant and `term_end` to exactly 365 days after `term_start` (the upper bound is exclusive — the term window covers instants from `term_start` up to but not including `term_end`), sets `term_index` to 1, accrues the plan's `annual_fee_cents` onto the customer's `billing_balance_cents`, and increments the membership's `version` by one.

While a membership is `ACTIVE`, an administrator may suspend it. The `ACTIVE → SUSPENDED` transition cascades down into the membership's visits, cancelling every one of its service visits currently in `SCHEDULED` or `DISPATCHED` status (each such visit transitions to `CANCELLED`), and increments the membership's `version` by one. A `SUSPENDED → ACTIVE` reinstatement simply returns the membership to `ACTIVE` and increments its `version` by one.

Cancellation is the member's prerogative (and is also available to an administrator). A membership may be cancelled from `ACTIVE`, `SUSPENDED`, or `RENEWAL_PENDING`; from any of these the membership transitions to the terminal `CANCELLED` state. Cancellation cascades more broadly than suspension: it cancels every one of the membership's service visits in `SCHEDULED`, `DISPATCHED`, or `EN_ROUTE` status (each to `CANCELLED`), expires any renewal offer for the membership currently in `PENDING` status (setting that offer to `EXPIRED`), and increments the membership's `version` by one.

### 3.4. Seasonal Rhythm: Renewal Offers and Auto-Renew

As a term nears its end, a `ContractAdmin` extends a **renewal offer** to an `ACTIVE` membership. Creating the offer requires the membership to be `ACTIVE` and requires that no renewal offer for that membership already sits in `PENDING`, `ACCEPTED`, or `AUTO_ACCEPTED` status; a second open offer is rejected with `ERR_OFFER_ALREADY_OPEN`. The offer is created with the `offered_plan_id` for the next term (which may equal the current plan) and an `expires_at` instant after which it can no longer be acted upon. As described in Section 2.8, the create also carries `expected_membership_version` and is subject to the stale-version guard. On success the system creates the offer in `PENDING` status, snapshots the offered plan's `annual_fee_cents` into the offer's `offered_annual_fee_cents` (a version-pinned price the offer will honor regardless of later plan changes), flips the membership from `ACTIVE` to `RENEWAL_PENDING`, and increments the membership's `version` by one. Renewal offers are listable both as a sub-collection of a membership and globally, filterable by `membership_id`, `offered_plan_id`, and `status`.

A renewal offer's `status` is one of `PENDING`, `ACCEPTED`, `AUTO_ACCEPTED`, `DECLINED`, or `EXPIRED`. The member decides its fate. Accepting an offer is permitted only when the offer is `PENDING`, the owning membership is in `RENEWAL_PENDING`, and the current clock is strictly before the offer's `expires_at`; an accept or decline at or after `expires_at` is rejected with `ERR_OFFER_EXPIRED`. A manual acceptance sets the offer's `status` to `ACCEPTED` and drives the membership's `RENEWAL_PENDING → ACTIVE` renewal: the membership's `plan_id` is set to the offer's `offered_plan_id`, the new `term_start` is set to the previous `term_end`, the new `term_end` is set to 365 days after the new `term_start`, `term_index` is incremented by one, the offer's `offered_annual_fee_cents` is accrued onto the customer's `billing_balance_cents`, and the membership's `version` is incremented by one. Because the new term resets the term window, the included-visit allowance is effectively refreshed for the renewed term. A manual decline is permitted when the offer is `PENDING` and the owning membership is `RENEWAL_PENDING`; it sets the offer's `status` to `DECLINED` and drives the membership's `RENEWAL_PENDING → LAPSED` transition, incrementing the membership's `version` by one.

Renewal can also happen automatically as time passes. The administrative clock can be advanced to a target instant, and as it crosses the `expires_at` of any still-`PENDING` offer, the offer resolves itself according to the membership's `auto_renew` flag. For an offer whose membership has `auto_renew` set to true, crossing `expires_at` auto-accepts the offer: its `status` becomes `AUTO_ACCEPTED` and it drives the same `RENEWAL_PENDING → ACTIVE` renewal (new term window, incremented `term_index`, accrued fee, version bump) as a manual acceptance. For an offer whose membership has `auto_renew` set to false, crossing `expires_at` expires the offer: its `status` becomes `EXPIRED` and it drives the membership's `RENEWAL_PENDING → LAPSED` transition. Both clock-driven resolutions require the offer to be `PENDING` and the clock to have reached or passed `expires_at`.

### 3.5. Booking and Routing Service Visits

A **service visit** is the unit of field work, booked by a `Dispatcher` (or a `ContractAdmin`) against a membership. A booking supplies the `membership_id`, the `visit_kind` — `SEASONAL`, `PRIORITY`, or `WARRANTY` — the `requested_at` instant the visit was requested, and the booked arrival window bounded by `window_start` and `window_end`. It may optionally name a `technician_id` up front, and it must carry `expected_membership_version` for the stale-version guard of Section 2.8. The referenced membership must be in `ACTIVE` status at booking time, or the request is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`. On a successful create the visit's `site_id` is copied from the membership's site, the visit opens in `SCHEDULED` status, and for priority visits the service-level evaluation described in Section 3.6 runs immediately. The visit also carries a computed `billable_charge_cents` (its charge at completion) and, for priority visits, a computed `sla_met` flag. Visits are listable globally and as a sub-collection of a membership, filterable by `membership_id`, `technician_id`, `site_id`, `status`, and `visit_kind`.

The window itself must be well-formed: `window_end` must be strictly later than `window_start`, both at booking and at reschedule, or the request fails with `ERR_INVALID_WINDOW`. A priority booking carries an additional temporal rule — its `requested_at` may not fall after its `window_start` (one cannot book a window that begins before the request instant) — and a violation of this also yields `ERR_INVALID_WINDOW`.

A visit's `status` advances through `SCHEDULED`, `DISPATCHED`, `EN_ROUTE`, `ON_SITE`, and `COMPLETED`, with `CANCELLED` and `NO_SHOW` as alternative terminal outcomes. While a visit is `SCHEDULED`, a `Dispatcher` may reschedule it, which keeps it in `SCHEDULED` (a self-loop) but moves `window_start` and `window_end` to new values. A reschedule re-runs every check that applied at booking: the window well-formedness rule, the technician daily-capacity rule, and, for priority visits, the SLA recomputation. A `Dispatcher` dispatches a `SCHEDULED` visit by naming the `technician_id` to assign; the `SCHEDULED → DISPATCHED` transition records that technician on the visit. Dispatch is the routing gate: the assigned technician's `region_code` must equal the visit site's `region_code` and the technician's `trade` must equal the membership plan's `trade`, or the dispatch is rejected with `ERR_TECH_REGION_TRADE_MISMATCH`. A dispatched visit can be recalled by a `Dispatcher`, a `DISPATCHED → SCHEDULED` revert that clears the assigned `technician_id` and returns the visit to the unassigned pool.

A `Dispatcher` may cancel a non-terminal visit (from `SCHEDULED`, `DISPATCHED`, or `EN_ROUTE`) to `CANCELLED`; when the visit was dispatched or en route, cancellation also clears the `technician_id`. A `Dispatcher` may mark a `DISPATCHED` visit as a no-show, a `DISPATCHED → NO_SHOW` transition that is permitted only once the current clock has reached or passed the visit's `window_end` (the window has elapsed without the technician departing). Every visit state change increments the visit's `version` by one.

### 3.6. Dispatch Safety: Double-Booking, Capacity, and the Priority SLA

Two distinct scheduling guards protect a technician's day, and they use different time granularities. The first is an overlap guard enforced at dispatch: the dispatched window may not overlap, under half-open interval semantics, any other non-terminal visit already in `DISPATCHED`, `EN_ROUTE`, or `ON_SITE` status for the same technician. Half-open means the interval runs from `window_start` up to but not including `window_end`, so two visits whose endpoints merely touch (one ending exactly when the next begins) do not overlap; any genuine intersection is rejected with `ERR_TECH_DOUBLE_BOOKED`. The second is a daily-capacity guard with date granularity: a technician may carry no more `SCHEDULED` plus `DISPATCHED` visits whose `window_start` falls on a given UTC calendar date than the technician's `daily_visit_capacity` allows. This capacity check buckets visits by calendar date rather than by minute-level interval, and it is applied at booking, at reschedule, and at dispatch; exceeding the cap is rejected with `ERR_TECH_DAILY_CAPACITY`.

The priority service-level agreement is evaluated for every priority visit at booking and re-evaluated on reschedule. The system computes the response latency as the number of hours between `requested_at` and `window_start` — the difference in seconds divided by 3600, kept as a fractional value — and sets `sla_met` to true when that latency is less than or equal to the plan's `sla_response_hours`, and to false when the latency is greater. The boundary is inclusive: a latency exactly equal to `sla_response_hours` counts as met. A breach does not block the booking — the visit is still created with `sla_met` recorded as false. For any visit whose `visit_kind` is not `PRIORITY`, `sla_met` is not evaluated and is left null.

### 3.7. On-Site Execution, Refrigerant Tracking, and the Mass-Balance Invariant

Only the assigned technician may carry a visit through its on-site phases, and only in order. From `DISPATCHED` the assigned technician departs (`DISPATCHED → EN_ROUTE`), then arrives (`EN_ROUTE → ON_SITE`); each step requires the acting technician's id to equal the visit's `technician_id`. While a visit is `ON_SITE` the technician records the work performed.

**Equipment** is registered by a `ContractAdmin` at a site. Each unit carries its `site_id`, a `model`, a `refrigerant_type` — `R410A`, `R32`, `R454B`, or `NONE`, defaulting to `NONE` for non-refrigerant equipment — a `nameplate_charge_grams` value (the full factory refrigerant charge, a non-negative integer that is 0 when the type is `NONE`), and a `warranty_expires_at` instant. Two independent status axes track the unit. The operational axis, `operational_status`, is one of `OPERATIONAL`, `NEEDS_SERVICE`, or `DECOMMISSIONED` and begins `OPERATIONAL`. The warranty axis, `warranty_status`, is one of `IN_WARRANTY`, `EXPIRED`, or `VOIDED` and begins `IN_WARRANTY`. The two axes move independently. The unit also tracks its live refrigerant mass in `current_charge_grams`, which is set to `nameplate_charge_grams` at registration and thereafter accumulates the refrigerant logs posted against it. When equipment is fetched, the system refreshes the warranty axis against the clock: if the current clock has reached or passed `warranty_expires_at` while the unit is still `IN_WARRANTY`, the warranty axis flips to `EXPIRED`. Equipment installed at a site is listable through the site's equipment sub-collection.

A **refrigerant log** records a single refrigerant movement during an on-site visit. The visit must be `ON_SITE` when the log is posted, or the post is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE` (the same code guards both visit-create-against-inactive-membership and refrigerant/part posting against a non-`ON_SITE` visit). A log names the `equipment_id` the refrigerant was moved on, the `action` (`ADD` or `RECOVER`), and the `grams` moved, which must be greater than 0. The equipment must sit at the same site as the visit — the equipment's `site_id` must equal the visit's `site_id`. Posting refrigerant is a regulated activity: the posting technician must hold EPA 608 certification, that is the assigned technician's `epa_certified` flag must be true, or the post is rejected with `ERR_TECH_NOT_CERTIFIED`. On a successful post the log's `posted_by_tech_id` is copied from the visit's `technician_id`, the equipment's `current_charge_grams` is adjusted, and the equipment's `version` is incremented by one. Refrigerant logs are listable both as a visit's sub-collection and globally, where they can be filtered by `equipment_id`, `posted_by_tech_id`, and the originating `visit_id`.

Refrigerant mass is a conserved quantity. A unit's `current_charge_grams` is reconstructed as its `nameplate_charge_grams` plus the total grams of all `ADD` logs minus the total grams of all `RECOVER` logs, with logs processed in ascending `created_at` order. Two invariants are enforced at posting time: a `RECOVER` may never drive `current_charge_grams` below 0, and an `ADD` may never drive `current_charge_grams` above `nameplate_charge_grams` (an overcharge); either violation is rejected with `ERR_REFRIGERANT_BALANCE`. The conservation property is exact — if a visit recovers some number of grams from a unit and later adds the same number of grams back to the same unit, the unit's `current_charge_grams` returns to its pre-visit value.

**Parts** consumed on a visit are recorded as part usages while the visit is `ON_SITE` (again, posting against a non-`ON_SITE` visit is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`). A part usage names the `part_name`, the `quantity` consumed (greater than 0), and the per-unit `list_price_cents` before discount (a non-negative integer). The system computes the line's `charged_cents` by taking the gross line amount — `list_price_cents` multiplied by `quantity` — multiplying it by one minus the member plan's `parts_discount_pct`, and rounding that discounted amount half-up to whole cents. When the plan's `parts_discount_pct` is 0, the charge equals `list_price_cents` times `quantity` exactly. Rounding is pinned at the line level: each part usage's `charged_cents` is rounded independently, and a membership's parts subtotal is the sum of the already-rounded line charges, never a single rounding of an un-rounded sum. On posting, the computed `charged_cents` is accrued onto the customer's `billing_balance_cents`.

### 3.8. Completing a Visit: Charge Assessment and Equipment Cascade

Only the assigned technician may complete a visit, and only from `ON_SITE`. For HVAC visits, completion additionally requires that every piece of equipment at the site that received refrigerant during the visit is mass-balance consistent — the mass-balance invariant of Section 3.7 must hold after completion. The `ON_SITE → COMPLETED` transition is terminal for the visit and triggers three coordinated effects, after which the visit's `version` is incremented by one.

First, the system assesses the charge and stamps it onto the visit's `billable_charge_cents`. A `WARRANTY` visit is always free: its `billable_charge_cents` is 0. A `PRIORITY` visit is always treated as out-of-plan and always bills the plan's `extra_visit_fee_cents` regardless of how many visits the term has already consumed. A `SEASONAL` visit is measured against the plan's included allowance: the system counts how many of this membership's seasonal visits already reached `COMPLETED` with their completion falling inside the current term window, excluding the visit being completed, and treats the visit being completed as the next one beyond that count. If that ordinal position exceeds the plan's `included_visits_per_year` — that is, if the count of prior in-term seasonal completions plus one is strictly greater than `included_visits_per_year` — the visit bills the plan's `extra_visit_fee_cents`; otherwise it bills 0. Whenever the assessed `billable_charge_cents` is greater than 0, that amount is accrued onto the customer's `billing_balance_cents`.

Second, the membership's `visits_consumed` becomes the recomputed count of the membership's visits that have reached `COMPLETED` within the current term window. This count is derived on read rather than written back, so it does not mutate the membership row or bump the membership's `version`.

Third, the system applies the deep-recovery equipment cascade. If any `RECOVER` refrigerant log posted during the visit left a piece of equipment's `current_charge_grams` below ten percent of its `nameplate_charge_grams`, that equipment's `operational_status` cascades from `OPERATIONAL` to `NEEDS_SERVICE`.

### 3.9. Equipment Service and Decommissioning

Beyond the automatic deep-recovery cascade, a `Technician` can manage an equipment unit's operational axis directly. Flagging a unit moves it `OPERATIONAL → NEEDS_SERVICE`; this touches only the operational axis and leaves `warranty_status` untouched. Clearing the flag moves it `NEEDS_SERVICE → OPERATIONAL`, but only once the unit has been recharged back into spec — its `current_charge_grams` must be at least ten percent of its `nameplate_charge_grams`. Each flag or clear increments the equipment's `version` by one.

A `ContractAdmin` decommissions a unit from either `OPERATIONAL` or `NEEDS_SERVICE` into the terminal `DECOMMISSIONED` operational state. Decommissioning enforces the EPA recovery rule: a unit may not retire while it still holds refrigerant, so its `current_charge_grams` must be exactly 0, otherwise the request is rejected with `ERR_REFRIGERANT_NOT_EVACUATED`. A successful decommission increments the equipment's `version` by one.

Technicians are themselves first-class records a `ContractAdmin` creates with a `full_name`, the `region_code` they service, their `trade` certification (`HVAC` or `PEST`), an `epa_certified` flag (defaulting to false), and a `daily_visit_capacity` of at least 1. Technicians are listable and filterable by `region_code` and `trade`.

### 3.10. Warranty Claims

A **warranty claim** is filed — by a `ContractAdmin` or a `Technician` — against a piece of equipment when a defect surfaces during warranty work. The claim names the `equipment_id` and the `origin_visit_id` (the warranty visit that surfaced the defect) and the `claimed_amount_cents` the customer claims (a non-negative integer). The origin must be legitimate: the origin visit's `visit_kind` must be `WARRANTY` and that visit's `site_id` must equal the equipment's `site_id`, or the filing is rejected with `ERR_CLAIM_ORIGIN_INVALID`. The claim opens in `SUBMITTED` status and also exposes `approved_amount_cents` (defaulting to 0) and `denial_reason` (defaulting to an empty string). Claims are listable and filterable by `equipment_id`, `origin_visit_id`, and `status`.

A claim's `status` runs `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `DENIED`, and `SETTLED`. A `ContractAdmin` adjudicates it. Starting review moves the claim `SUBMITTED → UNDER_REVIEW`, but only while the referenced equipment is still `IN_WARRANTY` on its warranty axis. From `UNDER_REVIEW` the claim forks. Approval moves it `UNDER_REVIEW → APPROVED` and records the authorized amount into `approved_amount_cents`; the authorized amount may not exceed the `claimed_amount_cents`, or the approval is rejected with `ERR_APPROVAL_EXCEEDS_CLAIM`. Denial moves it `UNDER_REVIEW → DENIED`, sets `approved_amount_cents` to 0, records the supplied `denial_reason`, and cascades across to the equipment by setting that equipment's `warranty_status` to `VOIDED` — a denied claim voids the warranty. Each of these transitions increments the claim's `version` by one.

Settlement closes an approved claim. The `APPROVED → SETTLED` transition credits the customer's ledger by exactly the `approved_amount_cents` — that amount is subtracted from the customer's `billing_balance_cents` — and increments the claim's `version` by one. When the authorized amount equals the full `claimed_amount_cents`, the ledger is credited by the full claimed amount; when the authorized amount is a partial amount strictly between 0 and the claimed amount, only that partial authorized amount is credited and the difference is never credited. A denied claim, having no settlement, moves the ledger by nothing.

### 3.11. The Administrative Test Clock

Because so much of this domain turns on time — term windows, SLA latency, offer expiry, no-show eligibility, and warranty lapse — the system exposes a logical UTC clock that a `ContractAdmin` controls for test-driving. One capability sets the clock to a supplied instant; another advances it toward a supplied instant. Both take their target as `to_iso8601`. Advancing the clock is not a passive change: as the clock crosses the `expires_at` of any still-`PENDING` renewal offer, that offer is resolved exactly as described in Section 3.4 — auto-accepted when its membership's `auto_renew` is true, expired when it is false — driving the membership's renewal cycle accordingly.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify an existing resource — including state transitions, retirements, and adjudications — return `200 OK`. The administrative clock operations also return `200 OK`. Each endpoint's request and response payloads, side effects, and guarding rules are described in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/home-services/service-plans` | Create a service plan template | ContractAdmin |
| GET | `/home-services/service-plans/{id}` | Fetch a service plan | ContractAdmin, Dispatcher, Customer |
| GET | `/home-services/service-plans` | List service plans | ContractAdmin, Dispatcher, Customer |
| POST | `/home-services/service-plans/{id}/retire` | Retire a plan | ContractAdmin |
| POST | `/home-services/customers` | Create a customer | ContractAdmin |
| GET | `/home-services/customers/{id}` | Fetch a customer | ContractAdmin, Customer |
| POST | `/home-services/sites` | Create a service site | ContractAdmin |
| GET | `/home-services/sites/{id}` | Fetch a site | ContractAdmin, Dispatcher, Customer |
| GET | `/home-services/sites` | List sites | ContractAdmin, Dispatcher, Customer |
| GET | `/home-services/sites/{id}/equipment` | List equipment at a site | ContractAdmin, Dispatcher, Customer, Technician |
| POST | `/home-services/equipment` | Register equipment at a site | ContractAdmin |
| GET | `/home-services/equipment/{id}` | Fetch equipment | ContractAdmin, Dispatcher, Customer, Technician |
| POST | `/home-services/equipment/{id}/flag-service` | Flag a unit as needing service | Technician |
| POST | `/home-services/equipment/{id}/clear-service` | Clear the service flag | Technician |
| POST | `/home-services/equipment/{id}/decommission` | Retire a unit | ContractAdmin |
| POST | `/home-services/technicians` | Create a technician | ContractAdmin |
| GET | `/home-services/technicians/{id}` | Fetch a technician | ContractAdmin, Dispatcher |
| GET | `/home-services/technicians` | List technicians | ContractAdmin, Dispatcher |
| POST | `/home-services/memberships` | Create a membership | ContractAdmin |
| GET | `/home-services/memberships/{id}` | Fetch a membership | ContractAdmin, Customer |
| GET | `/home-services/memberships` | List memberships | ContractAdmin, Customer |
| POST | `/home-services/memberships/{id}/activate` | Activate a pending membership | ContractAdmin |
| POST | `/home-services/memberships/{id}/suspend` | Suspend an active membership | ContractAdmin |
| POST | `/home-services/memberships/{id}/reinstate` | Reinstate a suspended membership | ContractAdmin |
| POST | `/home-services/memberships/{id}/cancel` | Cancel a membership | Customer, ContractAdmin |
| POST | `/home-services/memberships/{id}/renewal-offers` | Create a renewal offer | ContractAdmin |
| GET | `/home-services/memberships/{id}/renewal-offers` | List renewal offers for a membership | ContractAdmin, Customer |
| GET | `/home-services/memberships/{id}/service-visits` | List service visits for a membership | ContractAdmin, Dispatcher, Customer |
| GET | `/home-services/renewal-offers/{id}` | Fetch a renewal offer | ContractAdmin, Customer |
| GET | `/home-services/renewal-offers` | List renewal offers | ContractAdmin, Customer |
| POST | `/home-services/renewal-offers/{id}/accept` | Accept a renewal offer | Customer |
| POST | `/home-services/renewal-offers/{id}/decline` | Decline a renewal offer | Customer |
| POST | `/home-services/service-visits` | Book a service visit | Dispatcher, ContractAdmin |
| GET | `/home-services/service-visits/{id}` | Fetch a service visit | ContractAdmin, Dispatcher, Customer, Technician |
| GET | `/home-services/service-visits` | List service visits | ContractAdmin, Dispatcher, Technician |
| POST | `/home-services/service-visits/{id}/reschedule` | Move a scheduled visit's window | Dispatcher |
| POST | `/home-services/service-visits/{id}/dispatch` | Assign a technician and dispatch | Dispatcher |
| POST | `/home-services/service-visits/{id}/recall` | Recall a dispatched visit | Dispatcher |
| POST | `/home-services/service-visits/{id}/depart` | Technician departs toward the site | Technician |
| POST | `/home-services/service-visits/{id}/arrive` | Technician arrives on site | Technician |
| POST | `/home-services/service-visits/{id}/complete` | Complete the visit | Technician |
| POST | `/home-services/service-visits/{id}/cancel` | Cancel a non-terminal visit | Dispatcher, ContractAdmin |
| POST | `/home-services/service-visits/{id}/mark-no-show` | Mark a dispatched visit as a no-show | Dispatcher |
| POST | `/home-services/service-visits/{id}/refrigerant-logs` | Post a refrigerant ADD/RECOVER | Technician |
| GET | `/home-services/service-visits/{id}/refrigerant-logs` | List refrigerant logs for a visit | ContractAdmin, Technician, Dispatcher |
| GET | `/home-services/refrigerant-logs/{id}` | Fetch a single refrigerant log | ContractAdmin, Technician, Dispatcher |
| GET | `/home-services/refrigerant-logs` | List refrigerant logs | ContractAdmin, Technician, Dispatcher |
| POST | `/home-services/service-visits/{id}/part-usages` | Post a part consumed on a visit | Technician |
| GET | `/home-services/service-visits/{id}/part-usages` | List parts consumed on a visit | ContractAdmin, Technician, Dispatcher |
| POST | `/home-services/warranty-claims` | File a warranty claim | ContractAdmin, Technician |
| GET | `/home-services/warranty-claims/{id}` | Fetch a warranty claim | ContractAdmin, Customer, Technician |
| GET | `/home-services/warranty-claims` | List warranty claims | ContractAdmin, Customer, Technician |
| POST | `/home-services/warranty-claims/{id}/start-review` | Begin reviewing a submitted claim | ContractAdmin |
| POST | `/home-services/warranty-claims/{id}/approve` | Approve a claim with an authorized amount | ContractAdmin |
| POST | `/home-services/warranty-claims/{id}/deny` | Deny a claim | ContractAdmin |
| POST | `/home-services/warranty-claims/{id}/settle` | Settle an approved claim | ContractAdmin |
| POST | `/home-services/_clock/set_current_utc` | Set the logical UTC clock | ContractAdmin |
| POST | `/home-services/_clock/advance` | Advance the logical UTC clock | ContractAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SITE_OWNER_MISMATCH` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TECH_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_REFRIGERANT_BALANCE` | 422 Unprocessable Entity |
| `ERR_REFRIGERANT_NOT_EVACUATED` | 422 Unprocessable Entity |
| `ERR_TECH_REGION_TRADE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_TECH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_TECH_DAILY_CAPACITY` | 409 Conflict |
| `ERR_OFFER_ALREADY_OPEN` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_APPROVAL_EXCEEDS_CLAIM` | 422 Unprocessable Entity |
| `ERR_CLAIM_ORIGIN_INVALID` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
