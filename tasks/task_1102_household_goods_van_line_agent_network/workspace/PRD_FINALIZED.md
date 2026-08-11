# Household Goods Van Line Agent Network API — Product Requirements Document

## 1. Introduction

Interstate household-goods moving in the United States is operated by van lines — national carrier brands in the style of United and Mayflower — that own very little of the physical capacity that touches a shipment. The work is performed by a federated network of local agents, each certified to perform one or more of four functions on any given move: booking the order, performing origin services, hauling the shipment, and performing destination services. Coordinating four independent companies plus a shipper across a single move — under federal rules governing estimates, certified weighing, valuation coverage, and curbside collection — is the operational problem this API is built to solve.

This document specifies a REST API managing the full lifecycle of an interstate household-goods move: order registration, estimate issuance and acceptance under binding or non-binding pricing, agent staffing, valuation coverage election, certified weighment and the customer's re-weigh right, storage-in-transit with its permanent-storage cap, crew labor sourcing at both ends, delivery collection under the federal one-hundred-ten-percent rule, revenue distribution across the agents and the van line, and the claims and arbitration program that follows delivery. Every operation runs against a controllable logical clock rather than the wall clock, so that date-driven rules — estimate expiry, delivery spread windows, storage day caps, mediation cooling-off periods, and claim filing windows — remain deterministic and reproducible.

Because money changes hands at the curb and every cent of linehaul revenue is divided among up to five parties, the API treats all monetary figures as exact integer cents, pins rounding order wherever component rounding could diverge, and enforces segregation of duties wherever one operator's decision must be checked by a different operator.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, formats, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which that party acts. The API recognizes exactly eight roles, spelled exactly as follows: `VanLineAdmin`, `BookingAgent`, `OriginAgent`, `HaulingAgent`, `DestinationAgent`, `Customer`, `ClaimsAdjuster`, and `Arbitrator`. A request missing either header, or presenting a role outside these eight, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles authorized for the target endpoint — or, for an entity-backed role, whose `X-User-ID` does not resolve to an existing entity of the backing type — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `BookingAgent`, `OriginAgent`, `HaulingAgent`, or `DestinationAgent`, `X-User-ID` is the `id` of the acting `Agent`; ownership checks on any resource that references an `Agent` compare the resource's foreign-key field (for example, an assignment's `agent_id`) to `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`, and ownership checks compare the order's `customer_id` to `X-User-ID`. When `X-User-Role` is `VanLineAdmin`, `ClaimsAdjuster`, or `Arbitrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `offered_by_user_id` on a `Claim`, as `responded_by_user_id` or `decided_by_user_id` on a `Dispute`, or as `filer_user_id` on a filed `Dispute`) but never compares it to any entity's `id`.

Beyond role membership, order-scoped mutation endpoints apply an ownership scope: an agent-role caller must hold an assignment on the target order whose `agent_id` equals the caller's `X-User-ID`, whose `role` matches the caller's agent role, and whose status is `PROPOSED` or `CONFIRMED`; a `Customer` caller's `X-User-ID` must equal the order's `customer_id`; the opaque roles (`VanLineAdmin`, `ClaimsAdjuster`, `Arbitrator`) are exempt from this scoping. A caller who passes role authorization but fails this ownership scope is likewise rejected with `ERR_FORBIDDEN_ROLE`.

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

### 2.3. Pagination and List Filtering

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

Each list endpoint additionally accepts equality filters drawn from the resource's own fields. The agent list accepts `status` and `capability`. The customer list accepts no filters beyond pagination. The tariff list accepts `status`. The order list accepts `customer_id`, `tariff_id`, `authoritative_weight_ticket_id`, and `status`. The estimate list accepts `order_id`, `supersedes_estimate_id`, and `status`. The agent-assignment list accepts `order_id`, `agent_id`, `role`, and `status`. The valuation-coverage list accepts `order_id` and `status`. The weight-ticket list accepts `order_id`, `reweigh_request_id`, `supersedes_ticket_id`, and `ticket_kind`. The re-weigh-request list accepts `order_id`, `resulting_ticket_id`, and `status`. The warehouse list accepts `status`. The SIT-lot list accepts `order_id`, `warehouse_id`, and `status`. The crew-assignment list accepts `order_id`, `agent_id`, `service_end`, and `status`. The revenue-statement list accepts `order_id` and `status`. The claim list accepts `order_id`, `valuation_coverage_id`, and `status`. The dispute list accepts `claim_id`, `revenue_statement_id`, and `status`.

### 2.4. Common Resource Properties

Every primary resource — `Agent`, `Customer`, `Tariff`, `MoveOrder`, `Estimate`, `OrderAgentAssignment`, `ValuationCoverage`, `ReweighRequest`, `Warehouse`, `SITLot`, `CrewAssignment`, `RevenueStatement`, `Claim`, and `Dispute` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; refreshed on every change to the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations produced by cascade side effects originating on another resource. This field backs the optimistic concurrency control described in §2.7.

The `WeightTicket` resource is the single exception: as immutable scale evidence it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it. Every other resource follows the full convention above, providing a consistent audit trail and unique addressability.

### 2.5. The Logical Clock and Date Precision

The system never consults the wall clock. All time-dependent rules read a logical clock maintained by the server, whose startup default is exactly 2026-05-01T00:00:00Z; before any operator intervention the clock reads this default. A `VanLineAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Setting the clock re-evaluates the storage day-limit conversion (§3.5) for every lot still in storage against the new time.

Fields that carry a calendar date rather than an instant — the order's `pickup_date` and a crew assignment's `service_date`, together with the booking-computed `earliest_delivery_date` and `latest_delivery_date` derived from `pickup_date` — use day precision at midnight UTC (00:00:00Z), and all day arithmetic in this document is whole-day arithmetic on such midnight-normalized dates. When a client supplies one of the ingestible day-precision fields (`pickup_date`, `service_date`) with a time-of-day component, the server normalizes the value to midnight UTC (00:00:00 of the value's UTC calendar day) at intake, and the normalized value is what is stored and used in every comparison and computation. In responses, each of these four fields is rendered in the form `YYYY-MM-DDT00:00:00Z` with no fractional digits; the three-fractional-digit form of §2.2 and §2.4 remains reserved for instant-valued fields such as `api_request_timestamp`, `created_at`, and `updated_at`.

### 2.6. Money, Weight, and Rounding Discipline

All monetary values in the system are exact integer cents; no floating-point money is ever stored or returned. Wherever a multiplication or percentage produces a fractional cent, the result is rounded half up to the nearest whole cent. Estimated and final charge totals follow a pinned rounding order: every charge component is individually rounded to integer cents before any summation, and the total is the sum of those rounded components. Summing unrounded components and rounding once at the end is forbidden, because the two orders yield different cents.

Shipment weight is tracked in whole pounds. Conversions to hundredweight divide pounds by 100 and round up: any nonzero remainder of pounds over a whole hundredweight counts as a full additional hundredweight. Rates that express percentages, such as the tariff's fuel surcharge, are carried as decimal fractions (a ten percent surcharge is written as 0.10).

### 2.7. Optimistic Concurrency Control on Order Writes

Two write operations against a move order are protected by optimistic concurrency control: issuing an estimate on an order, and electing a valuation coverage on an order. Each requires the request to carry `expected_order_version`, a non-optional field holding the `version` of the order as the client last observed it. If the order's current `version` no longer matches — because another writer has advanced it since that read — the write is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). The protection exists because each of these writes supersedes an existing record: a newer estimate legitimately supersedes any prior issued or accepted estimate, and a new election legitimately supersedes the currently elected coverage, so a writer holding a stale order version would otherwise replace a revision it never observed. Endpoints not named here do not accept a version field at all.

### 2.8. Windows, Bands, and Half-Open Intervals

Three distinct interval disciplines recur across the API, and all three share the same half-open semantics: the lower bound is included and the upper bound is excluded.

A tariff's effective window runs from `effective_start` up to but not including `effective_end`, and `effective_end` must be strictly later than `effective_start`. Publishing a tariff is rejected with `ERR_TARIFF_WINDOW_OVERLAP` (HTTP 409) when its window intersects the window of any other already-published tariff, with one exception: pure adjacency, where the existing tariff's `effective_end` equals the new tariff's `effective_start`, is allowed.

A tariff's `mileage_bands` array consists of entries each carrying `min_miles`, `max_miles`, and a `rate_multiplier`. A band is selected when the order's mileage is at least the band's `min_miles` and strictly less than its `max_miles`, except that the final band includes its `max_miles` as well. The bands of a tariff must tile the mileage axis from zero without gaps and without overlaps.

A crew assignment's worked hours form a half-open interval that includes `start_hour` and excludes `end_hour`. When two confirmed crews of the same agent on the same service date have intersecting intervals, the later confirmation is rejected with `ERR_CREW_SCHEDULE_CONFLICT` (HTTP 409); back-to-back intervals, where one crew's `end_hour` equals the other's `start_hour`, do not intersect and are allowed.

### 2.9. Network Ledgers: Warehouse Capacity, Agent Earnings, and Quality Standing

Three running ledgers are maintained by cascade rather than by direct write, and every cascade-driven mutation refreshes `updated_at` and increments `version` on the mutated resource.

A warehouse's `occupied_cwt` is a ledger equal at all times to the sum of `stored_weight_cwt` over that warehouse's lots whose status is `IN_STORAGE`. The ledger is synchronized on every check-in (the lot's stored hundredweight is added), on every release (the stored hundredweight is subtracted as a compensating entry), and on every permanent-storage conversion (likewise subtracted).

An agent's `ytd_linehaul_share_cents` is a running ledger of linehaul earnings: when a revenue statement is created at delivery, each completed assignment's `split_amount_cents` is added to the holding agent's ledger.

An agent's `quality_score` starts at 100 and is recomputed whenever the order's statement accumulates chargebacks: the new score is one hundred minus the number of complete ten-thousand-cent blocks contained in the statement's cumulative `chargeback_total_cents` (that is, the chargeback total divided by ten thousand and rounded down to a whole number), and it never falls below zero.

### 2.10. Request Validation Pipeline and Nested Path Resolution

Every request is evaluated against a fixed validation pipeline, and a request rejected at an earlier stage never reaches a later one. The stages, in order, are:

1. **Authentication** — presence and validity of `X-User-ID` and `X-User-Role` (HTTP 401).
2. **Role authorization** — the caller's role must appear in the endpoint's authorized role list, and for entity-backed roles the `X-User-ID` must resolve to an existing entity of the backing type (HTTP 403).
3. **Ownership scoping** — the assignment- and customer-matching rules of §2.1 on order-scoped mutations (HTTP 403).
4. **Existence** — path-template resources are validated left to right, and body-referenced identifiers (such as `customer_id`, `tariff_id`, `agent_id`, `warehouse_id`, `claim_id`, and `revenue_statement_id`) must resolve to existing resources; the first missing identifier, scanning the path from left to right, yields `ERR_NOT_FOUND` (HTTP 404).
5. **Request-body well-formedness** — required fields present, types correct, enum values in range, unknown fields rejected, and structural rules such as gross weight being at least the tare weight, the end hour being later than the start hour, and the deductible being one of its allowed values (HTTP 400).
6. **Lifecycle-state gates** — from-state and sub-state preconditions on the target resource, endpoint by endpoint (HTTP 409). Where one endpoint carries several named state checks, §3 states their written evaluation order.
7. **Segregation of duties** — the payer-is-not-offeror and decider-is-not-responder rules (HTTP 403).
8. **Logical-clock gates** — pickup-date, estimate-expiry, claim-window, mediation cooling-off, and crew service-window checks (HTTP 422).
9. **Uniqueness and capacity constraints** — duplicate codes and emails, one-original-weighment, one-active-re-weigh, one-open-dispute, negotiation-round caps, agent status and capability, warehouse active status (HTTP 409, or 422 where §3 says so).
10. **Interval-conflict constraints** — tariff window overlap, crew schedule overlap, warehouse aggregate capacity (HTTP 409).
11. **Cross-entity reference integrity** — published-tariff coverage at registration, disputable-state requirements at dispute filing, crew service-end matching (HTTP 409 or 422 as §3 states).
12. **Money gates** — delivery collection, deferred-balance payment, settlement-offer caps, arbitration award ranges (HTTP 422).

This pipeline also governs nested resource retrieval: a request aimed at a resource beneath an order first confirms the order exists, then the child resource, and only then evaluates the operation's business rules, so an invalid container is reported before any child-level validation is attempted.

## 3. Business Logic & Workflows

### 3.1. Network Onboarding: Agents, Shippers, Tariffs, and Warehouses

A `VanLineAdmin` registers each network agent with its `legal_name`, a unique `agent_code` of four to eight characters (a code already on file is rejected with `ERR_DUPLICATE_AGENT_CODE`, HTTP 409), a non-empty `capabilities` list drawn from `BOOKING`, `ORIGIN`, `HAULING`, and `DESTINATION`, the agent's `home_market`, and an optional `commission_tier` of `STANDARD`, `PREFERRED`, or `PREMIER` that defaults to `STANDARD` and later drives the revenue-split bonus of §3.8. A new agent begins with `status` `ACTIVE`, a `quality_score` of 100, and a `ytd_linehaul_share_cents` ledger of 0. An agent's `status` thereafter walks `ACTIVE` to `SUSPENDED` (suspension), `SUSPENDED` back to `ACTIVE` (reactivation), or `SUSPENDED` to the terminal `TERMINATED` when a suspension call carries a payload with `terminal` set to true. Termination is refused with `ERR_AGENT_HAS_OPEN_WORK` while the agent still holds a `PROPOSED` or `CONFIRMED` assignment on any order that has not yet reached `DELIVERED`, `SETTLED`, `CLOSED`, or `CANCELLED`. Every one of these agent transitions bumps the agent's `version`.

Shippers are registered by a `VanLineAdmin` or a `BookingAgent` with `full_name`, `email`, and `phone`; the email must be unique across all customers, with duplicates rejected as `ERR_DUPLICATE_CUSTOMER_EMAIL`. A customer's `status` is `ACTIVE` from creation — it is the only customer state, and archival is out of scope.

Tariffs are the pricing backbone. A `VanLineAdmin` drafts a tariff with a unique `tariff_code` (duplicates rejected as `ERR_DUPLICATE_TARIFF_CODE`), the `effective_start` and `effective_end` of its effective window, the `base_rate_cents_per_cwt` linehaul base rate before any mileage-band multiplier, the `mileage_bands` array of band entries (each with `min_miles`, `max_miles`, and `rate_multiplier`, tiling from zero per §2.8), a `fuel_surcharge_pct` applied to the linehaul, the `sit_daily_rate_cents_per_cwt` storage rate, and the `hourly_labor_rate_cents` crew rate. A tariff is created in `DRAFT` and moves to `PUBLISHED` through publication, which enforces the window-overlap discipline of §2.8 and bumps the tariff's `version`; only `PUBLISHED` tariffs may back new orders.

Warehouses anchor the storage-in-transit program. Registration takes a `name`, the `market` served, and an aggregate `capacity_cwt` of at least 1; the warehouse starts with `occupied_cwt` at 0 and `status` `ACTIVE`. Deactivation flips the warehouse from `ACTIVE` to `INACTIVE` and blocks any new storage check-in, without disturbing lots already stored.

### 3.2. Order Registration and Agent Staffing

A `BookingAgent` registers a move order with a payload naming the `customer_id` of the shipper and the `tariff_id` of the chosen tariff, the `pricing_mode` — `BINDING` or `NON_BINDING`, immutable once registered — the `origin_city` and `origin_state`, the `destination_city` and `destination_state`, the certified `mileage` between them (at least 1), and the scheduled `pickup_date`. The referenced tariff must be `PUBLISHED` and its effective window must cover the pickup date, otherwise registration is rejected with `ERR_TARIFF_NOT_PUBLISHED`. On creation the order receives a sequential `order_number` in the VL-000001 style — a registration number used for identity only and never consulted by any decision — and lands in `REGISTERED` with `billing_status` `UNBILLED`. Registration also auto-creates the order's `BOOKING` assignment in `CONFIRMED` status, naming the registering agent through the caller's `X-User-ID` and snapshotting its `split_pct` at that moment.

The order's `status` axis walks `REGISTERED`, `BOOKED`, `IN_TRANSIT`, `IN_SIT`, `OUT_FOR_DELIVERY`, `DELIVERED`, and `SETTLED`, terminating at `CLOSED` or at `CANCELLED` from the early states. The `billing_status` axis is independent and walks `UNBILLED`, `PROVISIONALLY_BILLED`, `FINAL_BILLED`, and `PAID`. Weight fields (`estimated_weight_lbs`, `actual_weight_lbs`, `authoritative_weight_ticket_id`), the delivery window (`earliest_delivery_date`, `latest_delivery_date`), and the delivery money fields (`final_charges_cents`, `delivery_amount_due_cents`, `deferred_balance_cents`, `collected_at_delivery_cents`, `delivered_at`) all remain null until the lifecycle point that produces them.

Staffing the remaining three legs is the booking agent's job (a `VanLineAdmin` may also act): each proposal names an `agent_id` and a `role` of `ORIGIN`, `HAULING`, or `DESTINATION` and creates an assignment in `PROPOSED`. The named agent must be `ACTIVE` — assigning to a `SUSPENDED` or `TERMINATED` agent is rejected with `ERR_AGENT_SUSPENDED` — and its `capabilities` must include the proposed role, otherwise the proposal fails with `ERR_AGENT_CAPABILITY_MISSING` (HTTP 422). Confirmation is performed by the assigned agent itself: the caller's `X-User-ID` must equal the assignment's `agent_id` (mismatches fail with `ERR_FORBIDDEN_ROLE`), the agent must still be `ACTIVE`, and the order must still be `REGISTERED`. Confirmation snapshots the assignment's `split_pct` as the role's base percentage plus the agent's commission-tier bonus (the table lives in §3.8) and bumps the assignment's `version`. While the order is `REGISTERED`, the booking side may also release a `PROPOSED` assignment, moving it to the terminal `RELEASED`; the `BOOKING` assignment can never be released. Every registration-phase write — issuing an estimate, electing valuation coverage, and proposing, confirming, or releasing an agent assignment — requires the order to be `REGISTERED` and is otherwise rejected with `ERR_ORDER_NOT_REGISTERED`.

### 3.3. Estimates and Valuation: Pricing the Move

Issuing an estimate is a booking-side action on a `REGISTERED` order. The payload carries `estimate_kind`, which must equal the order's `pricing_mode` (a mismatch is rejected with `ERR_ESTIMATE_KIND_MISMATCH`, HTTP 422); `estimated_weight_lbs` of at least 1; an optional `packing_services_cents` defaulting to 0 and never negative; and `expected_order_version` per the concurrency rule of §2.7. The new estimate supersedes any prior `ISSUED` or `ACCEPTED` estimate on the same order — the prior estimate becomes `SUPERSEDED` with its `version` bumped, and when the superseded estimate had been `ACCEPTED`, the order's latched `estimated_weight_lbs` reverts to null until the replacement estimate is accepted. The new estimate records the replaced estimate as `supersedes_estimate_id` (null on the first estimate), computes `revision_number` as one greater than the superseded estimate's revision (1 for the first estimate on an order), stamps `issued_at` from the logical clock, and sets `expires_at` thirty days after issuance.

Estimate pricing follows a pinned component order. The linehaul component converts the estimated weight to hundredweight — pounds divided by 100, rounding any remainder up to the next hundredweight — selects the single tariff mileage band containing the order's mileage (lower bound inclusive, upper bound exclusive, final band inclusive), multiplies the hundredweight by the tariff's `base_rate_cents_per_cwt` and by that band's `rate_multiplier`, and rounds half up to integer cents; the result is `linehaul_cents`. The fuel component, `fuel_surcharge_cents`, is the rounded linehaul multiplied by the tariff's `fuel_surcharge_pct`, again rounded half up to integer cents. The valuation component, `valuation_premium_cents`, snapshots the premium of the order's currently `ELECTED` valuation coverage, and is 0 when no coverage is elected at issuance. Adding the estimate's `packing_services_cents` — already integer cents — yields `estimated_charges_cents` as the sum of the individually rounded components; per §2.6, summing unrounded components and rounding once is forbidden.

The customer answers an estimate while it is `ISSUED`. Acceptance additionally requires the order to still be `REGISTERED` (otherwise `ERR_ORDER_NOT_REGISTERED`) and the logical clock to be no later than `expires_at`; an accept attempted after expiry is rejected with `ERR_ESTIMATE_EXPIRED` (HTTP 422) and the estimate flips to `EXPIRED` within the same rejection. A successful acceptance moves the estimate to `ACCEPTED`, latches the estimate's `estimated_weight_lbs` onto the order, and bumps both the estimate's and the order's `version`. Declining moves an `ISSUED` estimate to the terminal `DECLINED`. Order cancellation voids any `ISSUED` or `ACCEPTED` estimate into `VOIDED`. The two pricing modes diverge later: under `BINDING`, the accepted estimate's weight and components govern the final invoice no matter what the scale later shows; under `NON_BINDING`, the estimate is advisory and final charges are recomputed from certified scale weight at delivery (§3.7).

Valuation coverage is elected by the booking agent or the customer while the order is `REGISTERED`, again carrying `expected_order_version` per §2.7. The `coverage_type` is `RELEASED_VALUE` or `FULL_VALUE_PROTECTION`. Under `RELEASED_VALUE` the `declared_value_cents` is forced to 0 and the `premium_cents` is always 0 — the carrier's liability is instead capped per pound at claim time (§3.9). Under `FULL_VALUE_PROTECTION`, the `declared_value_cents` must be at least 1 (otherwise `ERR_INVALID_REQUEST`), and the `deductible_cents` — defaulting to 0 and meaningful only for full-value protection — must be exactly 0, 25000, or 50000 (any other value is `ERR_INVALID_REQUEST`). The premium divides the declared value into whole one-hundred-dollar units (10000 cents each), rounding any remainder up to the next unit; multiplies the unit count by 85 cents; multiplies by the deductible factor — 1.00 for a deductible of 0, 0.85 for 25000, and 0.70 for 50000; and rounds the result half up to integer cents. A new election supersedes the order's currently `ELECTED` coverage into `SUPERSEDED` at any time before dispatch, and bumps the order's `version`; at dispatch the elected coverage locks (§3.4). A coverage's `status` is therefore one of `ELECTED`, `LOCKED`, or `SUPERSEDED`.

### 3.4. Booking, Weighment, and Dispatch

Once the paperwork is complete, the booking agent books the order. Booking requires the order to be `REGISTERED` (otherwise `ERR_ORDER_NOT_REGISTERED`) and then enforces three gates, evaluated in this written order: an `ACCEPTED` estimate exists whose kind matches the order's `pricing_mode` (else `ERR_NO_ACCEPTED_ESTIMATE`); an `ELECTED` valuation coverage exists (else `ERR_NO_VALUATION_COVERAGE`); and all four role assignments are `CONFIRMED` (else `ERR_AGENT_ROLES_INCOMPLETE` — the `BOOKING` leg is already `CONFIRMED` from registration, so the operative checks are `ORIGIN`, `HAULING`, and `DESTINATION`). Booking computes the contractual delivery spread window from the order's mileage: under 500 miles allows 2 transit days followed by a 2-day spread; 500 miles up to under 1500 allows 4 transit days and a 3-day spread; 1500 up to under 2500 allows 6 transit days and a 4-day spread; and 2500 miles and above, up to the table's 999999 ceiling, allows 8 transit days and a 5-day spread. A mileage of exactly 500 selects the 500-to-1500 band, not the first band. The `earliest_delivery_date` is the pickup date plus the transit days, and the `latest_delivery_date` is the earliest delivery date plus the spread days. The order lands in `BOOKED` with its `version` bumped.

Certified weighment is recorded by the hauling agent while the order is `BOOKED` or `IN_TRANSIT`; from any other state the write is rejected with `ERR_TRANSITION_NOT_ALLOWED`. The payload names the `scale_location`, the `weighed_at` timestamp, the `tare_weight_lbs` of the empty vehicle (at least 1), and the `gross_weight_lbs` of the loaded vehicle, which must be at least the tare weight (otherwise `ERR_INVALID_REQUEST`). Exactly one `ORIGINAL` ticket may exist per order: a second original weighment is rejected with `ERR_ORIGINAL_WEIGHT_EXISTS`, and any further weighment must come through the re-weigh program of §3.5. The ticket's `net_weight_lbs` is the gross weight minus the tare weight. Recording the original ticket makes it authoritative: the order's `authoritative_weight_ticket_id` is set to the new ticket, `actual_weight_lbs` is recomputed from it, and the order's `version` is bumped. On an original ticket the `ticket_kind` is `ORIGINAL` and both `reweigh_request_id` and `supersedes_ticket_id` are null. Recall from §2.4 that weight tickets are immutable evidence carrying no `updated_at` or `version`.

Dispatch is the hauling agent's act and is gated by four checks evaluated in this written order: the order is `BOOKED` (otherwise `ERR_TRANSITION_NOT_ALLOWED`); an `ORIGINAL` weight ticket exists on the order (else `ERR_WEIGHT_TICKET_REQUIRED`); every `CONFIRMED` origin-end crew assignment on the order has been `COMPLETED` (else `ERR_ORIGIN_SERVICES_INCOMPLETE`); and the logical clock has reached the order's `pickup_date` (else `ERR_PICKUP_DATE_NOT_REACHED`, HTTP 422). Dispatch locks the elected coverage — the `ELECTED` valuation coverage becomes `LOCKED` with its `version` bumped — moves `billing_status` from `UNBILLED` to `PROVISIONALLY_BILLED` with `delivery_amount_due_cents` provisionally set to the accepted estimate's `estimated_charges_cents`, and lands the order in `IN_TRANSIT` with its `version` bumped.

### 3.5. In Transit: Re-Weigh Rights and Storage-in-Transit

Either the customer or the booking agent may demand a re-weigh before delivery. The request records who demanded it as `requested_by_role` — `CUSTOMER` or `BOOKING_AGENT` — and requires the order to be `IN_TRANSIT` (otherwise `ERR_ORDER_NOT_IN_TRANSIT`). Two uniqueness limits apply: at most one non-terminal re-weigh request may exist on an order at a time, and at most one re-weigh may ever reach `APPLIED` on an order; either violation is rejected with `ERR_REWEIGH_ALREADY_USED`. A new request opens in `REQUESTED`.

The hauling agent performs the re-weigh while the request is `REQUESTED` (any other request state is `ERR_TRANSITION_NOT_ALLOWED`) and the order is `IN_TRANSIT` or `IN_SIT` (otherwise `ERR_ORDER_NOT_IN_TRANSIT`). Performance takes the same scale payload as an original weighment — `scale_location`, `weighed_at`, `tare_weight_lbs`, and `gross_weight_lbs` — and produces a `WeightTicket` whose `ticket_kind` is `REWEIGH`, whose `reweigh_request_id` names the request, and whose `supersedes_ticket_id` names the order's currently authoritative ticket as evidence lineage. The request's `resulting_ticket_id` is set to the new ticket and the request moves to `PERFORMED` with its `version` bumped.

Applying the re-weigh is the customer's right (a `VanLineAdmin` may also apply it). Apply requires the request to be `PERFORMED` — otherwise `ERR_REWEIGH_REQUEST_NOT_PERFORMED` — and the order to be `IN_TRANSIT` or `IN_SIT` (otherwise `ERR_ORDER_NOT_IN_TRANSIT`). On apply, the order's `authoritative_weight_ticket_id` switches to the resulting ticket, `actual_weight_lbs` is recomputed, the final-charges-and-cap computation of §3.7 is re-run so that `delivery_amount_due_cents` is refreshed with the one-hundred-ten-percent cap re-evaluated against the new net weight, the order's `version` is bumped, and the request becomes `APPLIED` (terminal). If the customer instead declines a performed re-weigh, the request becomes `DECLINED_BY_CUSTOMER` (terminal) and the original authoritative weight stands; declining likewise requires `PERFORMED`, failing with `ERR_REWEIGH_REQUEST_NOT_PERFORMED` otherwise. A request still `REQUESTED` may be cancelled by the customer or the booking agent, landing in `CANCELLED`. A re-weigh that was performed but never applied never blocks delivery: the delivery cascade flips it to `EXPIRED` and the original weight stands.

When a shipment must pause, the hauling or destination agent checks it into storage-in-transit. Check-in requires the order `IN_TRANSIT` (otherwise `ERR_ORDER_NOT_IN_TRANSIT`) and a payload naming the `warehouse_id`. The warehouse must be `ACTIVE` (else `ERR_WAREHOUSE_INACTIVE`) and must have aggregate room: its `occupied_cwt` plus the shipment's hundredweight — the order's `actual_weight_lbs` divided by 100 with any remainder rounded up — must not exceed its `capacity_cwt`, or the check-in is rejected with `ERR_WAREHOUSE_CAPACITY_EXCEEDED`. A successful check-in creates a `SITLot` in `IN_STORAGE` with `stored_weight_cwt` set to that hundredweight and `checked_in_at` stamped from the logical clock, adds the stored hundredweight to the warehouse ledger per §2.9 (bumping the warehouse's `version`), and moves the order from `IN_TRANSIT` to `IN_SIT` with its `version` bumped.

Storage accrues daily. A lot's `days_stored` is the count of whole days between `checked_in_at` and `released_at` — or, while the lot is still stored, the current logical clock — discarding any partial day; a same-day release therefore shows zero days. Billable days are `days_stored` capped at 180. The lot's `accrued_storage_cents` is `stored_weight_cwt` times the tariff's `sit_daily_rate_cents_per_cwt` times the billable days, computed live at read time while the lot is `IN_STORAGE` and frozen at release or conversion.

The 180-day rule converts storage to permanence. Whenever a lot's `days_stored` reaches 180 — the limit is re-evaluated on any read or mutation of the lot, and again whenever the logical clock is set — the lot auto-converts from `IN_STORAGE` to `CONVERTED_PERMANENT`: its accrual is frozen at the 180-day cap, the warehouse ledger subtracts the stored hundredweight (bumping the warehouse's `version`), and the lot's `version` is bumped. Conversion models the shipment passing into permanent storage under a new contract, and it matters downstream: only an `IN_STORAGE` lot blocks delivery, so a `CONVERTED_PERMANENT` lot has released its warehouse capacity and does not prevent the order from being delivered.

Release for final delivery is the destination agent's act, and the day-limit rule is evaluated first: if the lot has reached 180 days it converts to `CONVERTED_PERMANENT` and the release is rejected with `ERR_LOT_NOT_IN_STORAGE`; a lot already `RELEASED` or previously converted fails the same way. Otherwise the release moves the lot to `RELEASED` with `released_at` stamped from the clock and the accrual frozen, subtracts the stored hundredweight from the warehouse ledger as a compensating entry (warehouse `version` bumped), and moves the order from `IN_SIT` to `OUT_FOR_DELIVERY` with its `version` bumped. Release itself performs no crew check — crew discipline lives entirely on crew confirmation (§3.6).

### 3.6. Crew Labor at Origin and Destination

Crew labor is sourced at each end by the agent holding that end's role. The sourcing call carries `service_end` — `ORIGIN` or `DESTINATION` — a `service_date`, a `start_hour` and `end_hour`, and the `crew_size`. The sourcing agent is recorded as the crew assignment's `agent_id` from the caller's `X-User-ID`, and the `service_end` must match the role that agent holds on the order: an origin-end crew can only be sourced by the order's origin agent and a destination-end crew only by its destination agent, with mismatches failing the ownership scope as `ERR_FORBIDDEN_ROLE`. The `start_hour` runs from 0 to 23 and the `end_hour` from 1 to 24, and the end must be later than the start — violations are `ERR_INVALID_REQUEST`; per §2.8 the worked interval includes the start hour and excludes the end hour. The `crew_size` is at least 1. Once the order is `BOOKED` or beyond, the `service_date` must fall no earlier than the order's `pickup_date` and no later than thirty days after its `latest_delivery_date`, outside which the request is rejected with `ERR_SERVICE_DATE_OUT_OF_WINDOW` (HTTP 422). A new crew assignment opens in `REQUESTED` with `labor_hours` computed as the end hour minus the start hour.

The invoice is computed once at creation and frozen thereafter. Regular hours are `labor_hours` capped at 8 — a shift of exactly eight hours earns no overtime — and overtime hours are whatever remains beyond 8. Each worker earns the regular hours times the order's tariff `hourly_labor_rate_cents`, plus the overtime hours times that rate times one and a half, with only the overtime component rounded half up to integer cents. The crew's `invoice_amount_cents` is that per-worker amount multiplied by `crew_size`; the rounding is pinned so that the per-worker overtime is rounded before the crew-size multiplication, never after.

Confirming a crew booking is the sourcing agent's own act: the crew must be `REQUESTED` (otherwise `ERR_TRANSITION_NOT_ALLOWED`), the caller's `X-User-ID` must equal the crew's `agent_id` (else `ERR_FORBIDDEN_ROLE`), and no other `CONFIRMED` crew of the same agent on the same `service_date` may have a worked interval intersecting this one under the half-open rule of §2.8 — a conflict is rejected with `ERR_CREW_SCHEDULE_CONFLICT`, while back-to-back intervals are allowed. Marking the service performed requires the crew to be `CONFIRMED` and the same identity check, and the order must no longer be `REGISTERED` or `CANCELLED` (otherwise `ERR_TRANSITION_NOT_ALLOWED`); the crew becomes `COMPLETED`. Cancellation by the origin agent, the destination agent, or the booking agent is allowed from `REQUESTED` or `CONFIRMED` and lands the crew in the terminal `CANCELLED`; cancelling a `CONFIRMED` crew returns its hours to the agent's pool for that date as a compensating action, and an order-level cancellation cascades `REQUESTED` and `CONFIRMED` crews to `CANCELLED` with the same compensation. Later, statement finalization flips every `COMPLETED` crew on the order to `INVOICED` (§3.8). Two cross-links matter: dispatch refuses to proceed while any `CONFIRMED` origin crew is still uncompleted (§3.4), and the invoices of `COMPLETED` crews feed the accessorial shares in the revenue distribution (§3.8).

### 3.7. Delivery, the 110% Rule, and Settlement

Delivery is completed by the destination agent through four gates evaluated in this written order: the order is `IN_TRANSIT` or `OUT_FOR_DELIVERY` (from any other state, `ERR_TRANSITION_NOT_ALLOWED`); no SIT lot on the order is still `IN_STORAGE` (else `ERR_SHIPMENT_IN_STORAGE` — recall that a `CONVERTED_PERMANENT` lot does not block); no re-weigh request on the order is still `REQUESTED` (else `ERR_REWEIGH_PENDING`, and the customer must cancel the pending request first — a performed-but-unapplied re-weigh does not block and instead expires in the cascade below); and the payload's `collected_at_delivery_cents` equals the freshly recomputed `delivery_amount_due_cents` (a mismatch is `ERR_DELIVERY_PAYMENT_MISMATCH`, HTTP 422).

Final charges depend on the pricing mode. For a `BINDING` order the final invoice equals the accepted estimate's `estimated_charges_cents` verbatim — actual scale weight never changes it. For a `NON_BINDING` order the linehaul and fuel components are recomputed over the authoritative weight (the original weighment, or an applied re-weigh) using the linehaul algorithm of §3.3, and combined with the locked coverage's premium and the accepted estimate's packing charge. The federal collection cap is one hundred ten percent of the accepted estimate's `estimated_charges_cents`, rounded half up. The amount lawfully demandable at the curb, `delivery_amount_due_cents`, is the smaller of the final charges and the cap for a `NON_BINDING` order, and the full final charges for a `BINDING` order. The `deferred_balance_cents` is the final charges minus the delivery amount due — zero for `BINDING` orders, and zero whenever the final charges do not exceed the cap; the boundary is inclusive, so when the final charges equal the cap exactly, the whole amount is demandable and the deferred balance is zero.

A successful delivery sets `final_charges_cents`, refreshes `delivery_amount_due_cents` and `deferred_balance_cents`, records the collected amount in `collected_at_delivery_cents`, stamps `delivered_at` from the logical clock, and moves `billing_status` to `FINAL_BILLED` — and for a `BINDING` order straight on to `PAID` within the same transition. The order lands in `DELIVERED` with its `version` bumped, and three cascade hops follow. Hop one: the order's single `RevenueStatement` is created in `PROVISIONAL` with the revenue waterfall of §3.8 computed and its share fields written, and every `PERFORMED` re-weigh request on the order flips to `EXPIRED`. Hop two: every `CONFIRMED` agent assignment on the order becomes `COMPLETED` with its `split_amount_cents` written per the waterfall. Hop three: each completed assignment credits its `split_amount_cents` to the holding agent's `ytd_linehaul_share_cents` ledger, bumping each such agent's `version`.

Any deferred balance is collected after delivery by the customer or a `VanLineAdmin` with a payload `amount_cents`. The payment is permitted only while `billing_status` is `FINAL_BILLED` and a `deferred_balance_cents` greater than zero remains (otherwise `ERR_NO_BALANCE_DUE`), and the amount must equal the deferred balance exactly (otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`); a successful payment moves `billing_status` to `PAID` and bumps the order's `version`.

Two terminal exits close the order's story. A `VanLineAdmin` may close a `SETTLED` order, but only when no claim on the order remains in `FILED`, `OFFER_MADE`, `DISPUTED`, or `ACCEPTED` (else `ERR_OPEN_CLAIMS_EXIST`) and no dispute touching the order's claims or its statement remains in `OPENED`, `RESPONSE_FILED`, `ARBITRATION_DOCKETED`, or `DECIDED` (else `ERR_OPEN_DISPUTES_EXIST`); closure lands the order in `CLOSED` with its `version` bumped. Earlier, the booking agent or a `VanLineAdmin` may cancel from `REGISTERED` or `BOOKED` — from any other state the cancel is `ERR_TRANSITION_NOT_ALLOWED`. Cancellation voids every `ISSUED` or `ACCEPTED` estimate into `VOIDED`, supersedes the `ELECTED` valuation coverage into `SUPERSEDED`, releases every `PROPOSED` or `CONFIRMED` assignment into `RELEASED`, cancels every `REQUESTED` or `CONFIRMED` crew with crew hours returned to the agent-date pool, leaves `billing_status` at `UNBILLED`, and lands the order in `CANCELLED` with its `version` bumped.

### 3.8. Revenue Distribution, Statements, and Chargebacks

Exactly one `RevenueStatement` exists per order, created automatically at delivery in `PROVISIONAL` status. Its `linehaul_revenue_cents` is the final linehaul plus fuel surcharge — the split basis — while `accessorial_revenue_cents` is an informational total of the crew invoices, the accrued SIT storage, and the valuation premium. The statement's `chargeback_total_cents` starts at 0 and grows through claim settlements, arbitration awards, and manual chargebacks.

The waterfall divides `linehaul_revenue_cents` across the four `CONFIRMED` agent assignments in a pinned bucket order — `BOOKING` first, then `ORIGIN`, then `HAULING`, then `DESTINATION`. Each bucket's effective percentage is the role's base — ten percent for `BOOKING`, twenty percent for `ORIGIN`, fifty-four percent for `HAULING`, and ten percent for `DESTINATION` — plus the commission-tier bonus of the agent holding that assignment: no bonus for `STANDARD`, one percentage point for `PREFERRED`, and two percentage points for `PREMIER`. This effective percentage is the same figure frozen as the assignment's `split_pct` at confirmation. Each share is the basis times the effective percentage, rounded half up to integer cents, and is written to `booking_share_cents`, `origin_share_cents`, `hauling_share_cents`, and `destination_share_cents` respectively.

The van line takes the residual — the basis minus the four role shares — subject to a floor. The floor is four percent of the basis, rounded half up. When the residual falls short of the floor, the shortfall is carved out of the `HAULING` share — always `HAULING`, pinned, never pro-rated across buckets — and the van line's share is set to the floor. Finally, the premium of the order's `LOCKED` valuation coverage is added to `van_line_share_cents`: valuation premiums flow to the van line. Attributable accessorials ride on the assignments rather than on the linehaul shares: the `ORIGIN` assignment's `split_amount_cents` additionally receives the sum of the `invoice_amount_cents` of the order's `COMPLETED` origin-end crews, and the `DESTINATION` assignment's `split_amount_cents` receives the sum of the `COMPLETED` destination-end crews' invoices plus the accrued SIT storage. A conservation invariant holds at all times: the four role shares plus the van-line share net of the valuation premium equal `linehaul_revenue_cents` exactly.

Finalizing the statement is a `VanLineAdmin` act requiring the statement to be `PROVISIONAL` (otherwise `ERR_TRANSITION_NOT_ALLOWED`) with the order `DELIVERED`. Finalization moves the statement to `FINAL` with its `version` bumped and fires two cascades: the order moves from `DELIVERED` to `SETTLED` with its `version` bumped, and every `COMPLETED` crew assignment on the order flips to `INVOICED`. Manual chargebacks are posted by a `VanLineAdmin` against a `FINAL` statement — posting against a statement in any other state is rejected with `ERR_STATEMENT_NOT_FINAL` — carrying an `amount_cents` and a `reason`: the statement's `chargeback_total_cents` grows by the amount (statement `version` bumped), and the `HAULING` agent's `quality_score` is recomputed per §2.9 as one hundred minus the whole ten-thousand-cent blocks in the new cumulative chargeback total, floored at zero (agent `version` bumped). Reconciliation, also `VanLineAdmin`-only, requires the statement `FINAL` and no dispute referencing it in `OPENED`, `RESPONSE_FILED`, `ARBITRATION_DOCKETED`, or `DECIDED` (otherwise `ERR_OPEN_DISPUTES_EXIST`); the statement lands in the terminal `RECONCILED` with its `version` bumped.

### 3.9. Claims, Disputes, and the Arbitration Program

A customer files a loss or damage claim once the order is `DELIVERED`, `SETTLED`, or `CLOSED` — filing earlier is rejected with `ERR_ORDER_NOT_DELIVERED` — and no later than 270 days after the order's `delivered_at`, beyond which filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422). The payload carries a `description` of the loss, a `claimed_amount_cents` of at least 1, and a `claimed_item_weight_lbs` of at least 1; at filing the claim captures the order's `LOCKED` valuation coverage into `valuation_coverage_id`, stamps `filed_at` from the logical clock, and opens in `FILED` with `round_count` at 0 and `offer_amount_cents`, `offered_by_user_id`, and `settled_amount_cents` still null.

Settlement offers are made by a `ClaimsAdjuster` while the claim is `FILED` or `DISPUTED` (from any other state, `ERR_TRANSITION_NOT_ALLOWED`), via a payload `offer_amount_cents`. The lawful ceiling depends on the captured coverage. Under a `RELEASED_VALUE` coverage the liability cap is sixty cents per pound times the claim's `claimed_item_weight_lbs`, regardless of any declared value. Under `FULL_VALUE_PROTECTION` the cap is the coverage's `declared_value_cents` minus its `deductible_cents`, floored at zero, independent of item weight. The maximum lawful offer is the smaller of the claimed amount and the liability cap; an offer exactly equal to the maximum is allowed, and anything above it is rejected with `ERR_OFFER_EXCEEDS_VALUATION_CAP` (HTTP 422). A successful offer records `offer_amount_cents` and the adjuster's identity in `offered_by_user_id`, and the claim moves to `OFFER_MADE` with its `version` bumped.

The customer answers an offer in one of three ways. Rejecting it requires `round_count` still below the hard cap of three negotiation rounds — a rejection at three rounds is rejected with `ERR_CLAIM_ROUNDS_EXHAUSTED`, further negotiation is forbidden, and the customer must turn to the arbitration program; a successful rejection increments `round_count` and returns the claim to `DISPUTED`, from which the adjuster may offer again under the same rules. Accepting the offer sets `settled_amount_cents` to the current `offer_amount_cents`, moves the claim to `ACCEPTED`, and fires two cascades: the order's revenue statement adds the settled amount to its `chargeback_total_cents` (statement `version` bumped), and the `HAULING` agent's `quality_score` is recomputed per §2.9 from the new chargeback total (agent `version` bumped). Withdrawing is available from `FILED`, `OFFER_MADE`, or `DISPUTED` and lands the claim in the terminal `WITHDRAWN`.

Payment of an accepted claim is a `VanLineAdmin` act under segregation of duties: the paying operator's `X-User-ID` must differ from the claim's `offered_by_user_id`, so the adjuster who made the accepted offer can never be the one who pays it — violations are `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); when the acceptance came from arbitration, `offered_by_user_id` holds the arbitrator's identifier and the same rule keeps that arbitrator from paying. Payment moves the claim from `ACCEPTED` to the terminal `PAID` and, as a cascade, closes every dispute referencing this claim that is still `OPENED`, `RESPONSE_FILED`, `ARBITRATION_DOCKETED`, or `DECIDED`.

When negotiation stalls, either side's next step is a dispute. A customer or any agent-role operator may open one, with a payload naming exactly one subject — a `claim_id` or a `revenue_statement_id`, never both and never neither (violations are `ERR_DISPUTE_SUBJECT_INVALID`, HTTP 422) — and a `subject_amount_cents` of at least 1. The subject must be in a disputable state: a claim subject must be `DISPUTED` with at least one rejected round behind it (`round_count` of 1 or more), and a statement subject must be `FINAL` — filing against a statement that is not `FINAL` is rejected with `ERR_STATEMENT_NOT_FINAL`, and a subject failing these state requirements is `ERR_DISPUTE_SUBJECT_INVALID`. Only one open dispute may exist per subject: opening another while one is `OPENED`, `RESPONSE_FILED`, `ARBITRATION_DOCKETED`, or `DECIDED` fails with `ERR_DISPUTE_ALREADY_OPEN`. Opening records `opened_by_role` — `CUSTOMER` for a shipper filer, `AGENT` for any agent filer — and `filer_user_id` from the caller's `X-User-ID`, and the dispute opens in `OPENED` with `responded_at`, `responded_by_user_id`, `escalated_at`, `decision_amount_cents`, `fee_allocated_to`, and `decided_by_user_id` all still null.

The van line answers through a `VanLineAdmin`, optionally attaching a `response_note`: the response stamps `responded_at` from the logical clock, records `responded_by_user_id`, and moves the dispute from `OPENED` to `RESPONSE_FILED`. Thereafter the filer — and only the filer, with `X-User-ID` equal to `filer_user_id` (otherwise `ERR_FORBIDDEN_ROLE`) — may escalate to arbitration, but only once at least fourteen days have elapsed since `responded_at`; earlier escalation is rejected with `ERR_MEDIATION_PERIOD_NOT_ELAPSED` (HTTP 422). Escalation moves the dispute to `ARBITRATION_DOCKETED`, stamps `escalated_at`, and sets `filing_fee_cents` to the program's fixed filing fee of 25000 cents.

An `Arbitrator` decides a docketed dispute under the second segregation-of-duties rule: the decider's `X-User-ID` must differ from `responded_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), so the operator who filed the van line's response can never arbitrate the same dispute. The award `decision_amount_cents` must lie between zero and `subject_amount_cents`, both ends inclusive — anything outside is `ERR_DECISION_OUT_OF_RANGE` (HTTP 422). The filing fee is allocated by comparing the award to the amount in controversy using exact integer cross-multiplication, never floating-point division: the fee falls to `RESPONDENT` when five times the award is at least four times the amount in controversy — an award of exactly eighty percent included; it falls to `FILER` when five times the award is at most one times the amount in controversy — an award of exactly twenty percent included; and in every other case the fee is `SPLIT`. The decision records `decided_by_user_id`, computes `fee_allocated_to` as just described, and moves the dispute to `DECIDED` with its `version` bumped, then cascades according to the subject: for a claim dispute, the referenced claim moves to `ACCEPTED` with `settled_amount_cents` set to the award and `offered_by_user_id` set to the arbitrator's identifier, firing the same chargeback and quality-score cascades as a negotiated acceptance; for a revenue dispute, the award is added to the statement's `chargeback_total_cents` as a cascade adjustment.

Closure and withdrawal end the dispute. A `VanLineAdmin` may close a `DECIDED` dispute; for a claim dispute the referenced claim must already be `PAID` (otherwise `ERR_CLAIM_NOT_PAID`), while a revenue dispute carries no additional condition. The filer may instead withdraw while the dispute is `OPENED` or `RESPONSE_FILED`, again with `X-User-ID` equal to `filer_user_id`, landing it in `WITHDRAWN`. Both `CLOSED` and `WITHDRAWN` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource — registering an agent, customer, tariff, warehouse, or order, or adding an estimate, assignment, coverage, weight ticket, re-weigh request, SIT lot, crew assignment, claim, or dispute — return `201 Created`. Operations that modify an existing resource, including every state-transition action and the logical-clock setter, return `200 OK`. The table below is deliberately a summary: each operation's request body, validation behavior, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-05-01T00:00:00Z) | VanLineAdmin |
| POST | `/agents` | Register a network agent | VanLineAdmin |
| GET | `/agents` | List agents | All roles |
| GET | `/agents/{id}` | Get one agent | All roles |
| POST | `/agents/{id}/suspend` | Suspend an agent; with a terminal payload, terminate from SUSPENDED when no open work remains | VanLineAdmin |
| POST | `/agents/{id}/reactivate` | Reactivate a suspended agent | VanLineAdmin |
| POST | `/customers` | Register a shipper | VanLineAdmin, BookingAgent |
| GET | `/customers` | List customers | All roles |
| GET | `/customers/{id}` | Get one customer | All roles |
| POST | `/tariffs` | Create a tariff in DRAFT | VanLineAdmin |
| POST | `/tariffs/{id}/publish` | Publish a tariff, rejecting window overlap with other published tariffs | VanLineAdmin |
| GET | `/tariffs` | List tariffs | All roles |
| GET | `/tariffs/{id}` | Get one tariff | All roles |
| POST | `/orders` | Register a move order; auto-creates the CONFIRMED BOOKING assignment for the registering agent | BookingAgent |
| GET | `/orders` | List orders | All roles |
| GET | `/orders/{id}` | Get one order | All roles |
| POST | `/orders/{id}/book` | Book the order after estimate acceptance, valuation election, and full role staffing | BookingAgent |
| POST | `/orders/{id}/dispatch` | Dispatch the shipment, requiring the original weighment and completed origin services | HaulingAgent |
| POST | `/orders/{id}/deliver` | Complete delivery, collecting exactly the capped amount, and fire the statement and split cascades | DestinationAgent |
| POST | `/orders/{id}/close` | Close a settled order with no open claims or disputes | VanLineAdmin |
| POST | `/orders/{id}/cancel` | Cancel a REGISTERED or BOOKED order, releasing assignments, voiding estimates, and cancelling crews | BookingAgent, VanLineAdmin |
| POST | `/orders/{id}/payments` | Collect the deferred balance of a delivered order | Customer, VanLineAdmin |
| POST | `/orders/{id}/estimates` | Issue an estimate, superseding any prior issued or accepted estimate (OCC on the order version) | BookingAgent |
| GET | `/estimates` | List estimates | All roles |
| GET | `/estimates/{id}` | Get one estimate | All roles |
| POST | `/estimates/{id}/accept` | Customer accepts an issued estimate; expired estimates flip to EXPIRED in the rejection | Customer |
| POST | `/estimates/{id}/decline` | Customer declines an issued estimate | Customer |
| POST | `/orders/{id}/agent-assignments` | Propose an ORIGIN, HAULING, or DESTINATION agent assignment | BookingAgent, VanLineAdmin |
| POST | `/order-agent-assignments/{id}/confirm` | The assigned agent confirms its own assignment, snapshotting the split percentage | OriginAgent, HaulingAgent, DestinationAgent |
| POST | `/order-agent-assignments/{id}/release` | Release a PROPOSED non-BOOKING assignment while the order is REGISTERED | BookingAgent, VanLineAdmin |
| GET | `/order-agent-assignments` | List agent assignments | All roles |
| GET | `/order-agent-assignments/{id}` | Get one agent assignment | All roles |
| POST | `/orders/{id}/valuation-coverages` | Elect valuation coverage, superseding any elected coverage pre-dispatch (OCC on the order version) | BookingAgent, Customer |
| GET | `/valuation-coverages` | List valuation coverages | All roles |
| GET | `/valuation-coverages/{id}` | Get one valuation coverage | All roles |
| POST | `/orders/{id}/weight-tickets` | Record the ORIGINAL certified weighment (one per order) | HaulingAgent |
| GET | `/weight-tickets` | List weight tickets | All roles |
| GET | `/weight-tickets/{id}` | Get one weight ticket | All roles |
| POST | `/orders/{id}/reweigh-requests` | Demand a re-weigh before delivery | Customer, BookingAgent |
| POST | `/reweigh-requests/{id}/perform` | Perform the re-weigh, producing a REWEIGH weight ticket | HaulingAgent |
| POST | `/reweigh-requests/{id}/apply` | Apply the re-weigh, switching the authoritative weight and recomputing the delivery cap | Customer, VanLineAdmin |
| POST | `/reweigh-requests/{id}/decline` | Decline the performed re-weigh; the original weight stands | Customer |
| POST | `/reweigh-requests/{id}/cancel` | Cancel a pending re-weigh request | Customer, BookingAgent |
| GET | `/reweigh-requests` | List re-weigh requests | All roles |
| GET | `/reweigh-requests/{id}` | Get one re-weigh request | All roles |
| POST | `/warehouses` | Register a storage-in-transit warehouse | VanLineAdmin |
| POST | `/warehouses/{id}/deactivate` | Deactivate a warehouse, blocking new check-ins | VanLineAdmin |
| GET | `/warehouses` | List warehouses | All roles |
| GET | `/warehouses/{id}` | Get one warehouse | All roles |
| POST | `/orders/{id}/sit-lots` | Check the shipment into storage-in-transit with an aggregate capacity check | HaulingAgent, DestinationAgent |
| POST | `/sit-lots/{id}/release` | Release the lot for delivery; the day-limit rule may auto-convert the lot first | DestinationAgent |
| GET | `/sit-lots` | List SIT lots | All roles |
| GET | `/sit-lots/{id}` | Get one SIT lot, with day-limit re-evaluation applied on read | All roles |
| POST | `/orders/{id}/crew-assignments` | Source crew labor at origin or destination; the invoice is computed at creation | OriginAgent, DestinationAgent |
| POST | `/crew-assignments/{id}/confirm` | Confirm a crew booking under the half-open overlap rule | OriginAgent, DestinationAgent |
| POST | `/crew-assignments/{id}/complete` | Mark the crew service performed | OriginAgent, DestinationAgent |
| POST | `/crew-assignments/{id}/cancel` | Cancel a requested or confirmed crew; confirmed hours return to the agent-date pool | OriginAgent, DestinationAgent, BookingAgent |
| GET | `/crew-assignments` | List crew assignments | All roles |
| GET | `/crew-assignments/{id}` | Get one crew assignment | All roles |
| GET | `/revenue-statements` | List revenue statements | All roles |
| GET | `/revenue-statements/{id}` | Get one revenue statement | All roles |
| POST | `/revenue-statements/{id}/finalize` | Finalize the statement, cascading the order to SETTLED and crews to INVOICED | VanLineAdmin |
| POST | `/revenue-statements/{id}/chargebacks` | Post a manual chargeback against the HAULING agent on a FINAL statement | VanLineAdmin |
| POST | `/revenue-statements/{id}/reconcile` | Reconcile a FINAL statement with no open disputes | VanLineAdmin |
| POST | `/orders/{id}/claims` | File a loss/damage claim after delivery, capturing the locked valuation coverage | Customer |
| GET | `/claims` | List claims | All roles |
| GET | `/claims/{id}` | Get one claim | All roles |
| POST | `/claims/{id}/offer` | Make a settlement offer, capped by the captured coverage | ClaimsAdjuster |
| POST | `/claims/{id}/accept` | Customer accepts the current offer, firing the chargeback cascade | Customer |
| POST | `/claims/{id}/reject-offer` | Customer rejects the offer, consuming one of three negotiation rounds | Customer |
| POST | `/claims/{id}/pay` | Pay an accepted claim; the payer must differ from the offering adjuster | VanLineAdmin |
| POST | `/claims/{id}/withdraw` | Withdraw an open claim | Customer |
| POST | `/disputes` | Open a dispute on a disputed claim or a FINAL revenue statement | Customer, BookingAgent, OriginAgent, HaulingAgent, DestinationAgent |
| GET | `/disputes` | List disputes | All roles |
| GET | `/disputes/{id}` | Get one dispute | All roles |
| POST | `/disputes/{id}/respond` | File the van line's response, starting the fourteen-day cooling-off | VanLineAdmin |
| POST | `/disputes/{id}/escalate-to-arbitration` | Filer escalates after the cooling-off; the filing fee attaches | Customer, BookingAgent, OriginAgent, HaulingAgent, DestinationAgent |
| POST | `/disputes/{id}/decide` | Arbitrator renders the decision with fee allocation and subject cascades | Arbitrator |
| POST | `/disputes/{id}/close` | Close a decided dispute; claim disputes require the claim paid | VanLineAdmin |
| POST | `/disputes/{id}/withdraw` | Filer withdraws an open or responded dispute | Customer, BookingAgent, OriginAgent, HaulingAgent, DestinationAgent |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status code. The conditions under which each error is raised are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_ORDER_NOT_REGISTERED` | 409 |
| `ERR_NO_ACCEPTED_ESTIMATE` | 409 |
| `ERR_NO_VALUATION_COVERAGE` | 409 |
| `ERR_AGENT_ROLES_INCOMPLETE` | 409 |
| `ERR_TRANSITION_NOT_ALLOWED` | 409 |
| `ERR_WEIGHT_TICKET_REQUIRED` | 409 |
| `ERR_ORIGIN_SERVICES_INCOMPLETE` | 409 |
| `ERR_ORDER_NOT_IN_TRANSIT` | 409 |
| `ERR_SHIPMENT_IN_STORAGE` | 409 |
| `ERR_REWEIGH_PENDING` | 409 |
| `ERR_REWEIGH_REQUEST_NOT_PERFORMED` | 409 |
| `ERR_STATEMENT_NOT_FINAL` | 409 |
| `ERR_CLAIM_NOT_PAID` | 409 |
| `ERR_LOT_NOT_IN_STORAGE` | 409 |
| `ERR_ORDER_NOT_DELIVERED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PICKUP_DATE_NOT_REACHED` | 422 |
| `ERR_ESTIMATE_EXPIRED` | 422 |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 |
| `ERR_MEDIATION_PERIOD_NOT_ELAPSED` | 422 |
| `ERR_SERVICE_DATE_OUT_OF_WINDOW` | 422 |
| `ERR_DUPLICATE_AGENT_CODE` | 409 |
| `ERR_DUPLICATE_CUSTOMER_EMAIL` | 409 |
| `ERR_DUPLICATE_TARIFF_CODE` | 409 |
| `ERR_ORIGINAL_WEIGHT_EXISTS` | 409 |
| `ERR_REWEIGH_ALREADY_USED` | 409 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_CLAIM_ROUNDS_EXHAUSTED` | 409 |
| `ERR_ESTIMATE_KIND_MISMATCH` | 422 |
| `ERR_AGENT_SUSPENDED` | 409 |
| `ERR_AGENT_CAPABILITY_MISSING` | 422 |
| `ERR_AGENT_HAS_OPEN_WORK` | 409 |
| `ERR_WAREHOUSE_INACTIVE` | 409 |
| `ERR_WAREHOUSE_CAPACITY_EXCEEDED` | 409 |
| `ERR_TARIFF_WINDOW_OVERLAP` | 409 |
| `ERR_CREW_SCHEDULE_CONFLICT` | 409 |
| `ERR_TARIFF_NOT_PUBLISHED` | 409 |
| `ERR_DISPUTE_SUBJECT_INVALID` | 422 |
| `ERR_DELIVERY_PAYMENT_MISMATCH` | 422 |
| `ERR_NO_BALANCE_DUE` | 422 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_OFFER_EXCEEDS_VALUATION_CAP` | 422 |
| `ERR_DECISION_OUT_OF_RANGE` | 422 |
| `ERR_OPEN_CLAIMS_EXIST` | 409 |
| `ERR_OPEN_DISPUTES_EXIST` | 409 |
