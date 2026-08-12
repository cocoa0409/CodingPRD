# Pet Waste Removal API — Product Requirements Document

## 1. Introduction

This document specifies a route-based pet-waste removal and yard-service platform. The business sells subscription packages for recurring yard cleanup — residential customers with one or two dogs, and multifamily or HOA-managed properties whose shared common areas need daily attention — and dispatches field technicians along planned service routes. Revenue arrives monthly per subscription, but the actual unit of work is the visit, and each visit may be customized with add-on services such as sanitizing and deodorizing. Because customers travel, dogs misbehave, gates jam, and weather intervenes, the platform must handle skips, vacation holds, missed arrivals, and post-hoc satisfaction recovery alongside the happy path.

Three forces shape the design. First, pricing is non-trivial: a monthly fee is built up from a base rate, a yard-size tier, a pet-count tier, and (for HOA common areas) a multifamily multiplier, and that monthly fee is then amortized across an estimated number of visits per month to yield a per-visit charge. Second, the field operation is state-heavy: a visit moves from scheduled, to en-route, to on-site, to completed, and along the way pet-safety acknowledgements, route-capacity constraints, technician certifications, and time-window conflicts all gate what is allowed. Third, the books must reconcile: credits for vacation skips and dissatisfied customers flow onto invoices, a customer's running credit balance offsets future totals, and an invoice is only finalized once the billing period has fully closed.

The audience for this document is the engineering team building the service. It assumes no prior domain knowledge and is the sole product specification.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two HTTP headers: `X-User-ID` and `X-User-Role`. If either header is missing, malformed, or names a role the platform does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. If the role is recognized but is not permitted to invoke the endpoint in question, the request is rejected with `ERR_UNAUTHORIZED`. The role catalogue is fixed and spelled exactly as follows.

- `Customer` — the end customer who owns yards and subscriptions.
- `Technician` — a field technician running a route.
- `OperationsManager` — back-office operations role with broad write access.
- `BillingAdmin` — finance role; owns invoices and dispute resolution.

How `X-User-ID` is interpreted depends on the role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; the same ownership rule applies to any resource that references a `Technician`. When `X-User-Role` is `OperationsManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

Authorization failures surface as `ERR_UNAUTHORIZED` (HTTP 403) before any business rule is evaluated. One role-specific check is elevated into the error catalogue: when a route's `assigned_technician_id` does not equal the acting technician's `id`, the rejection is `ERR_ROUTE_TECH_MISMATCH` (HTTP 403), not the generic `ERR_UNAUTHORIZED`. Resource-ownership comparisons (for example a `Customer` acting on another customer's resource) are evaluated only after every relevant path- and body-supplied id has been resolved (steps 3 and 4 of the validation order in §2.9) and before any state-machine or business-rule validation.

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

Requests to paths the API does not define, or using methods a defined path does not support, are rejected with `ERR_NOT_FOUND` (HTTP 404). A malformed or non-object JSON request body is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.3. Pagination

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and has a maximum of 100. The `offset` parameter defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List results are returned sorted by `created_at` ascending, with ties broken by creation (insertion) order. The `meta` envelope for list responses includes the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full filtered set size (not the size of the returned page) and `has_more` indicates whether further pages exist beyond the current `offset` plus returned `limit`. List endpoints additionally accept exact-match filter query parameters, applied before pagination: `GET /api/customers` filters by `email`; `GET /api/yards` by `customer_id` and `service_region_code`; `GET /api/property-access-profiles` by `yard_id`; `GET /api/subscription-plans` by `plan_status`; `GET /api/subscriptions` by `customer_id`, `yard_id`, `plan_id`, `pending_plan_change_id`, and `status`; `GET /api/service-routes` by `service_date`, `service_region_code`, `route_status`, and `assigned_technician_id`; `GET /api/visits` by `subscription_id`, `service_route_id`, `status`, and `scheduled_date`; `GET /api/invoices` by `customer_id` and `invoice_status`; `GET /api/invoice-line-items` by `invoice_id`, `visit_id`, `applied_addon_id`, and `line_type`; and `GET /api/satisfaction-reports` by `customer_id`, `visit_id`, and `report_status`. The date-valued filters (`service_date`, `scheduled_date`) match by calendar day. When the acting role is `Customer`, list responses are scoped to resources the customer owns, and passing a `customer_id` filter other than the caller's own id is rejected with `ERR_UNAUTHORIZED`.

### 2.4. Resource Identity and Common Fields

Every persistent resource has an `id` field carrying a server-minted UUID with no type prefix. All resources with the standard common-field set additionally expose `created_at` and `updated_at` — both ISO 8601 UTC timestamps with three fractional digits — and a `version` integer that starts at 1 on creation and is incremented by one on every mutation to the resource (every mutation also refreshes `updated_at`). The one exception to the common-field rule is `InvoiceLineItem`, which carries only `id` and `created_at`; `InvoiceLineItem` does not have `updated_at` and does not have `version`, because line items are immutable once written onto an invoice.

### 2.5. Money, Precision, and Rounding

All monetary amounts are integer cents. There is no floating-point money anywhere in the system. Where a calculation involves division or a multiplier, the rounding rule is round-half-up at the granularity the rule specifies, and each calculation below names the exact step at which rounding occurs. Where a calculation yields basis points (route load), the rule is integer floor division. Where a calculation yields a non-monetary rolling average (satisfaction), the final result is rounded half-up to two decimal places.

### 2.6. The Logical Clock and Scheduled Actions

The platform keeps a logical clock. At server startup the clock reads exactly `2026-05-01T00:00:00Z`; before any explicit set call, the clock reads that default and does not fall back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. All date and time comparisons in this document — visit windows, vacation-window starts, invoice period ends, "today" — are evaluated against this logical clock, never against wall time.

Two system-driven scheduled actions exist, both exposed as admin-only test-driving capabilities so tests can run them synchronously. The first applies every `SCHEDULED` `VacationWindow` whose `start_date` is at or before the current logical time, transitioning each due window to `APPLIED` and cascading the visit-skip effects described later; the endpoint returns the list of `applied_window_ids`. The second runs an end-of-day sweep for the current date, transitioning `SCHEDULED` visits past their window to `MISSED`, and returns the list of `missed_visit_ids`. The clock-set endpoint returns the new logical time as `data.current_utc`; advancing the clock also applies any staged subscription plan changes whose effective date has been reached (see §3.3).

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control. The rule is the same shape for both: the request must carry a non-optional expected-version field; if the value does not match the current `version` of the parent entity being modified, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here do not take any version field. On both guarded endpoints the expected-version comparison is evaluated after the state-transition validity check and before the action's remaining business rules.

The first guarded endpoint is the plan-change action on a `Subscription`. The request must carry `expected_subscription_version` matching the subscription's current `version`. If another writer has advanced the subscription's version since the client last read it — for example by activating, pausing, or staging a different plan — the plan-change request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a subscription state it has not observed.

The second guarded endpoint is the finalize action on an `Invoice`. The request must carry `expected_invoice_version` matching the invoice's current `version`. If another writer has advanced the invoice's version since the client last read it — for example because a vacation-window application or a satisfaction resolution posted new line items onto this invoice in the interim — the finalize request is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Route Capacity and Load Accounting

Every `ServiceRoute` tracks a `committed_visit_count` — the number of visits on the route whose status is `SCHEDULED`, `EN_ROUTE`, or `ON_SITE` — and a derived `route_load_factor_bp` in basis points. The load factor is the committed count multiplied by 10000 and divided by `max_visit_capacity`, computed with integer floor division. The constant 10000 basis points represents a fully loaded route. When the load factor would reach or exceed 10000, the platform rejects any further visit assignment to that route with `ERR_ROUTE_AT_CAPACITY` (HTTP 409). The committed count and load factor are recomputed on every visit mutation that affects the route — creation, route reassignment, completion, skip, miss, and cancel.

### 2.9. Validation Order and Error Discipline

Validations apply in a fixed priority order, and the order matters because a single bad request may violate several rules at once. The order is as follows.

1. Authentication headers present and well-formed — otherwise `ERR_UNAUTHENTICATED`.
2. Role permitted to call the endpoint — otherwise `ERR_UNAUTHORIZED`.
3. Every path-parameter id resolves to an existing entity, evaluated left-to-right along the URL — otherwise `ERR_NOT_FOUND`.
4. Every foreign-key id in the request body (`customer_id`, `yard_id`, `plan_id`, every entry of `addon_ids`, `service_route_id`, `visit_id`, and analogous fields) resolves to an existing entity — otherwise `ERR_REFERENCE_NOT_FOUND`.
5. The requested state-machine transition is valid from the entity's current state — otherwise `ERR_INVALID_STATE`.
6. For any state-mutating action taken by the `Customer` role — creating a subscription, activating, pausing, resuming, or cancelling a subscription, creating a vacation window, skipping a visit, filing a satisfaction report — the customer's `account_status` must be `ACTIVE`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`. This check applies to exactly those eight actions and no others.
7. Subscription activation and resume require the linked yard's access profile to be in `VERIFIED` status — otherwise `ERR_ACCESS_NOT_VERIFIED`.
8. Visit arrival requires the pet-safety acknowledgement when the yard's `pet_aggression_flag` is not `NONE` — otherwise `ERR_PET_SAFETY_ACK_REQUIRED`.
9. Yard creation or update requires `hoa_account_code` whenever `is_multifamily_common_area` is true — otherwise `ERR_HOA_CODE_REQUIRED`.
10. Plan scope must match yard scope: the plan's `applies_to_multifamily` must equal the yard's `is_multifamily_common_area` — otherwise `ERR_PLAN_SCOPE_MISMATCH`. This check applies when a subscription is created, when a plan change is staged, and when a subscription is activated.
11. The yard referenced by a new subscription must belong to the same customer — otherwise `ERR_YARD_OWNERSHIP_MISMATCH`.
12. A vacation window's `start_date` must not be later than its `end_date`, and `start_date` must not be in the past relative to the current logical date — otherwise `ERR_INVALID_WINDOW`.
13. A vacation window must not overlap (closed-interval overlap on dates) any other `SCHEDULED` or `APPLIED` vacation window on the same subscription — otherwise `ERR_WINDOW_OVERLAP`.
14. A visit's `scheduled_window_start` must be strictly earlier than `scheduled_window_end`, and the duration between them must be at least thirty minutes — otherwise `ERR_INVALID_TIME_WINDOW`.
15. A new visit on a route must not have a scheduled window that overlaps an existing visit on the same route, where each existing visit's window is expanded by a fifteen-minute buffer on both sides (the buffer runs from fifteen minutes before the existing visit's window start to fifteen minutes after its window end) and the intersection test is half-open — otherwise `ERR_VISIT_WINDOW_CONFLICT`.
16. Adding a visit to a route must leave the route's `route_load_factor_bp` strictly below 10000 — otherwise `ERR_ROUTE_AT_CAPACITY`.
17. Invoice finalize requires `billing_period_end` to be at or before the current logical time — otherwise `ERR_PERIOD_NOT_CLOSED`.
18. Payment recording requires the submitted `amount_cents` to exactly equal the invoice's `total_due_cents` — no overpayment, no underpayment — otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`.
19. A satisfaction resolution credit must be at least 0 and at most 100000 cents (a $1000 cap on any single resolution) — otherwise `ERR_CREDIT_OUT_OF_RANGE`.
20. A visit cannot be scheduled for a subscription in `CANCELLED` status, nor for a yard whose access profile is not `VERIFIED` at schedule time — otherwise `ERR_SUBSCRIPTION_NOT_SERVICEABLE`.

Malformed bodies, missing required fields, and wrong-typed fields are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Onboarding Customers, Yards, and Access Profiles

A `OperationsManager` onboards a new customer by supplying the customer's `full_name`, `email`, and `phone`. Technicians are onboarded separately by an `OperationsManager`, who supplies the technician's `full_name`, a unique `employee_code` (a duplicate is rejected with `ERR_INVALID_REQUEST`), and an optional `certified_for_aggressive_pets` flag defaulting to false; the technician's `active` flag defaults to true, and an inactive technician blocks publication of any route they are assigned to (`ERR_TECH_INACTIVE`, §3.5). The `email` must be unique across customers — a duplicate is rejected with `ERR_INVALID_REQUEST` (HTTP 400); the `phone` is stored as the primary contact in E.164 format. The resulting `Customer` record starts with `account_status` set to `ACTIVE`, a `credit_balance_cents` of 0, `lifetime_visits_completed` at 0, and `satisfaction_rolling_avg` set to null (no reports yet exist).

Once a customer exists, either an `OperationsManager` or the `Customer` themselves may register a serviceable yard. The payload contains the owning `customer_id`, the street `address_line1`, `city`, the two-letter `state_code`, and the `postal_code`. Two numeric attributes drive pricing downstream: `yard_size_sqft`, the serviceable area in square feet, constrained to lie between 1 and 200000 inclusive; and `pet_count`, the number of dogs regularly using the yard, constrained to lie between 0 and 20 inclusive. Values outside these ranges are rejected with `ERR_INVALID_REQUEST` (HTTP 400). A boolean `is_multifamily_common_area` defaults to false but, when true, marks the yard as an HOA or multifamily shared space and switches the pricing formula to the multifamily branch. Whenever `is_multifamily_common_area` is true, an `hoa_account_code` referencing the managing HOA billing account is required — its absence triggers `ERR_HOA_CODE_REQUIRED`. The `service_region_code` identifies the routing region and is later used to match yards to routes; it is a required field at yard creation.

Every yard has at most one `PropertyAccessProfile`, and creating the profile is a distinct step performed by an `OperationsManager` or the `Customer`. The profile captures the `gate_access_code`, free-form `gate_instructions` for the technician, and a `pet_on_premises` boolean that flags whether dogs are likely to be present during a visit; all three are required at creation, and a yard that already has a profile rejects a second creation attempt with `ERR_INVALID_REQUEST` (HTTP 400). The `pet_aggression_flag` accepts exactly one of `NONE`, `CAUTION`, or `AGGRESSIVE` and defaults to `NONE` when omitted; a flag of `AGGRESSIVE` forces a technician safety acknowledgement before any visit can be marked on-site. A newly created profile starts in `access_status` `VERIFICATION_PENDING`, with `suspension_reason` null.

An `OperationsManager` can move a profile from `VERIFICATION_PENDING` to `VERIFIED` by verifying it; verification requires the `gate_access_code` to be non-empty, and an empty or missing code is rejected with `ERR_GATE_CODE_REQUIRED`. The same verify action also lifts a profile out of `SUSPENDED` back to `VERIFIED`, clearing `suspension_reason` to null. An `OperationsManager` may also suspend a verified profile — typically because a gate is broken or a pet incident occurred — which moves the profile from `VERIFIED` to `SUSPENDED` and writes the supplied `reason` into `suspension_reason`. Suspending a profile does not cancel any active subscription on the yard, but it does block any subsequent activation or resume attempt with `ERR_ACCESS_NOT_VERIFIED`, which is the intended serialization point between access revocation and service resumption. Finally, an `OperationsManager` may force a verified profile back to `VERIFICATION_PENDING` via a require-reverification action, which carries no payload and simply resets the status.

Yard attributes are not frozen at creation. An `OperationsManager` or the owning `Customer` may update `yard_size_sqft`, `pet_count`, `is_multifamily_common_area`, `hoa_account_code`, or `service_region_code`. Updates are partial — omitted fields keep their current values — and the `hoa_account_code` requirement is evaluated against the merged post-update state. Each such change cascades: any subscription on the yard that is currently `ACTIVE` has its `monthly_fee_cents_snapshot` recomputed using the forward-looking variant of the monthly-fee calculation described later, so that billing always reflects the yard's current physical reality.

### 3.2. Building the Plan and Add-on Catalogue

Subscription plans are managed exclusively by `OperationsManager`. To define a plan, the manager supplies a unique `plan_code` (for example `RES_WEEKLY_1` or `HOA_DAILY`), a human-readable `display_name`, and a `visit_frequency` drawn from exactly `WEEKLY`, `BIWEEKLY`, `TWICE_WEEKLY`, or `DAILY`. The boolean `applies_to_multifamily` declares whether the plan is restricted to HOA common-area yards. The pricing inputs are `base_monthly_fee_cents` (a non-negative integer), two parallel arrays for yard tiers — `yard_tier_thresholds` (ascending square-foot thresholds) and `yard_tier_surcharges_cents` (per-tier monthly surcharges in cents, one entry longer than the thresholds array to cover the implicit top tier) — and two parallel arrays for pet tiers — `pet_tier_thresholds` (ascending pet-count thresholds) and `pet_tier_surcharges_cents`. The optional `multifamily_multiplier_bp` is a basis-points multiplier applied when the yard is a multifamily common area, defaulting to 10000 (that is, a 1.00× multiplier). At definition time the pricing inputs are validated: each thresholds array must be strictly ascending, each surcharges array must contain exactly one more entry than its thresholds array (this one-longer rule applies to the pet tiers exactly as to the yard tiers), `base_monthly_fee_cents` must be non-negative, and `plan_code` must be unique across plans — any violation is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new plan's `plan_status` starts at `ACTIVE` and may later transition to `RETIRED`; a retired plan cannot be activated against.

Add-ons are also managed by `OperationsManager`. Each `ServiceAddon` has a unique `addon_code` (the canonical pair is `SANITIZE` and `DEODORIZE`), a `display_name`, and a non-negative `price_cents_per_visit` representing the flat per-visit price whenever the add-on is applied. Add-ons start with `addon_status` `ACTIVE` and may be retired to `RETIRED`. The `addon_code` must be unique across add-ons and `price_cents_per_visit` must be non-negative; violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.3. Subscriptions: Creation, Activation, Pause, Resume, and Cancel

A subscription ties together a customer, a yard, and a plan. Either an `OperationsManager` or the `Customer` may create one by supplying `customer_id`, `yard_id`, and `plan_id`. Two structural checks guard creation: the referenced yard must belong to the referenced customer (otherwise `ERR_YARD_OWNERSHIP_MISMATCH`), and the plan's `applies_to_multifamily` must agree with the yard's `is_multifamily_common_area` (otherwise `ERR_PLAN_SCOPE_MISMATCH`). A new subscription starts in `status` `DRAFT`, with `started_on`, `next_billing_anchor_date`, and `monthly_fee_cents_snapshot` not yet meaningful, and `pending_plan_change_id` and `plan_change_effective_date` both null.

Activation moves the subscription from `DRAFT` to `ACTIVE` and is performed by the `Customer`. Activation enforces four preconditions, evaluated in this order: the customer's `account_status` must be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`); the yard's access profile must exist and be in `VERIFIED` status (else `ERR_ACCESS_NOT_VERIFIED`); the referenced plan must have `plan_status` `ACTIVE` (else `ERR_PLAN_RETIRED`); and the plan's scope must still match the yard's scope (else `ERR_PLAN_SCOPE_MISMATCH`). When activation succeeds, `started_on` is set to the current logical time, `next_billing_anchor_date` is set to the calendar-anchored first day of the next month, `monthly_fee_cents_snapshot` is computed via the forward-looking monthly-fee calculation, and the system generates the initial sequence of visits for the current period according to the plan's `visit_frequency`, each new visit starting in `SCHEDULED`. Generated visits begin on the current logical date and recur at the plan's cadence — every 7 days for `WEEKLY`, every 14 days for `BIWEEKLY`, alternating 3- and 4-day gaps for `TWICE_WEEKLY` (day offsets floor(7k/2) for k = 0, 1, 2, …), and every day for `DAILY` — up to but excluding `next_billing_anchor_date`, each with a default window of 08:00–17:00 UTC, no route, and no add-ons. Activation also increments the subscription's `version` by one.

Pausing moves an `ACTIVE` subscription to `PAUSED` and is available only when no visit on the subscription is currently `EN_ROUTE` or `ON_SITE`; if one is, the pause is rejected with `ERR_VISIT_IN_FLIGHT`. On a successful pause, every `SCHEDULED` visit on the subscription whose `scheduled_date` is strictly after today transitions to `CANCELLED` with `skip_source` set to `CUSTOMER_REQUEST`. Resuming reverses a pause: the `Customer` moves a `PAUSED` subscription back to `ACTIVE`, subject to the access profile existing and being `VERIFIED` (else `ERR_ACCESS_NOT_VERIFIED`) and the customer's `account_status` being `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`). Resuming generates a fresh sequence of visits for the remainder of the current period using the forward-looking variant.

Cancelling a subscription is permitted from either `ACTIVE` or `PAUSED`, and drives the subscription into its terminal `CANCELLED` state. The cascade on cancel has two parts: every non-terminal visit on the subscription transitions to `CANCELLED` with `skip_source` set to `CUSTOMER_REQUEST`, and any staged plan change is discarded by clearing `pending_plan_change_id` and `plan_change_effective_date` to null.

A plan change can be staged while a subscription is in any status other than `CANCELLED` — that is, from `DRAFT`, `ACTIVE`, or `PAUSED`; the staged plan's `plan_status` is not consulted at stage time. The `Customer` submits a `new_plan_id` together with `expected_subscription_version` carrying the client's last observed `version` of the subscription; if the version no longer matches, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) per the optimistic-concurrency rule. When accepted, the staged plan's id is written into `pending_plan_change_id` and `plan_change_effective_date` is set to the next billing anchor (for a `DRAFT` subscription, whose anchor is not yet set, the first day of the month following the current logical date); the staged change becomes effective at that anchor, applied lazily — when the logical clock is next set or a subscription resource is next read at or after the anchor — at which point the subscription's plan is swapped, both pending fields are cleared, the monthly fee snapshot is recomputed (only when the subscription is `ACTIVE`), and the subscription's `version` is incremented by one. Staging also increments the subscription's `version` by one. Plan-scope compatibility is re-checked at stage time (else `ERR_PLAN_SCOPE_MISMATCH`).

### 3.4. Pricing the Monthly Fee

The monthly subscription fee is the heart of the pricing engine. It is computed in two variants that share the same tiered-pricing core.

The core formula proceeds as follows. Start with the plan's `base_monthly_fee_cents`. Determine the yard tier by counting how many entries of `yard_tier_thresholds` are less than or equal to the yard's `yard_size_sqft`; that count (between zero and the number of thresholds) indexes into `yard_tier_surcharges_cents` to yield the yard surcharge. Apply the same procedure to pets: count how many entries of `pet_tier_thresholds` are less than or equal to `pet_count`, and index into `pet_tier_surcharges_cents` to yield the pet surcharge. The subtotal is the base plus the yard surcharge plus the pet surcharge. If the yard's `is_multifamily_common_area` is true, the fee is the subtotal multiplied by the plan's `multifamily_multiplier_bp` and divided by 10000 — where 10000 basis points represents a 1.00× multiplier — rounded half-up to whole cents. If the yard is not multifamily, the fee is the subtotal as-is.

The FORWARD_LOOKING variant runs at activation, at resume, on any yard change while the subscription is `ACTIVE`, and whenever a staged plan change becomes effective. It uses the yard's current `yard_size_sqft` and `pet_count` at computation time and stores the result on `monthly_fee_cents_snapshot`. The RECONCILED variant runs at invoice finalize time to produce the `SUBSCRIPTION_FEE_PRORATED` line for the period; it re-reads the yard at finalize time and prorates the fee by the ratio of days-active-in-period to days-in-period, rounding half-up on a per-day basis.

The per-visit charge is a separate calculation that amortizes the monthly fee. It runs in a PROVISIONAL variant at schedule time (stored on `provisional_visit_charge_cents`) and in a FINAL variant at completion, skip, or miss (stored on `final_visit_charge_cents`). The evaluation order is pinned. First, estimate the average number of visits per month from the plan's `visit_frequency`: `WEEKLY` corresponds to 4.33 visits per month, `BIWEEKLY` to 2.17, `TWICE_WEEKLY` to 8.67, and `DAILY` to 30. Second, the base per-visit amount is the subscription's `monthly_fee_cents_snapshot` divided by that average, rounded half-up to whole cents. Third, the add-on total is computed by de-duplicating repeated entries of `addon_ids` and resolving each distinct entry against `ServiceAddon` rows whose `addon_status` is `ACTIVE` and summing their `price_cents_per_visit`, with one bundle rule: when both `SANITIZE` and `DEODORIZE` are present on the same visit, the sum of those two add-on prices is discounted by 1500 basis points — that is, multiplied by 8500 and divided by 10000, rounded half-up once on the bundle pair — before being added to any other add-on prices. Fourth, the per-visit charge is the base per-visit amount plus the add-on total.

The FINAL variant differs by outcome. For a `COMPLETED` visit, the charge is recomputed using the add-ons attached to the visit at completion time. For a `SKIPPED` or `MISSED` visit, the final charge is always 0 regardless of add-ons.

### 3.5. Routing and Field Execution

Operations builds a `ServiceRoute` for each service date. Creating a route requires a `route_code` unique within its `service_date` — the same code may be reused on a different calendar day, and a duplicate on the same day is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — the `service_date` (stored as supplied; all comparisons against it use its calendar date), the `service_region_code` the route serves, and a `max_visit_capacity` of at least 1 (smaller values are rejected with `ERR_INVALID_REQUEST`). The `assigned_technician_id` may be left null at planning time and filled in later. A new route starts in `route_status` `PLANNED` with `committed_visit_count` 0 and `route_load_factor_bp` 0.

Scheduling a visit is something either an `OperationsManager` or the `Customer` may do, by supplying `subscription_id`, `scheduled_date`, `scheduled_window_start`, `scheduled_window_end`, optionally a `service_route_id`, and optionally an array `addon_ids`. The window must be internally valid (start strictly before end, at least thirty minutes long, else `ERR_INVALID_TIME_WINDOW`); the subscription must be serviceable (not `CANCELLED`, and the yard's access profile `VERIFIED` at schedule time, else `ERR_SUBSCRIPTION_NOT_SERVICEABLE`); if a route is supplied, the visit's window must not overlap any existing non-terminal visit on the same route once each existing visit's window is expanded by fifteen minutes on each side, with the intersection treated as half-open (else `ERR_VISIT_WINDOW_CONFLICT`); and the assignment must leave the route's `route_load_factor_bp` below 10000 (else `ERR_ROUTE_AT_CAPACITY`). On creation, `provisional_visit_charge_cents` is computed via the PROVISIONAL per-visit charge, and if a route was supplied the route's `committed_visit_count` is incremented and `route_load_factor_bp` recomputed. The `tech_safety_ack_at` field starts null. The `skip_source` field takes one of the values `VACATION`, `CUSTOMER_REQUEST`, `TECH_CANNOT_ACCESS`, `PET_SAFETY`, or `OTHER` and starts null. It is written when a visit enters `SKIPPED` (`VACATION` for vacation-window skips, `CUSTOMER_REQUEST` for customer-initiated skips) and when a visit enters `MISSED` (`OTHER`); the subscription pause and cancel cascades also stamp `CUSTOMER_REQUEST` on the visits they drive to `CANCELLED`. A visit cancelled directly via its own cancel action keeps `skip_source` null.

An `OperationsManager` may reassign a visit's route at any time before the visit reaches a terminal state by supplying a new `service_route_id`; the operation decrements the old route's committed count, increments the new route's, and recomputes `route_load_factor_bp` on both. The same window-conflict and capacity checks apply to reassignment as to initial scheduling, except that the visit itself is excluded from the conflict scan and reassigning a visit to the route it is already on contributes no additional committed count to the capacity check.

Publishing moves a route from `PLANNED` to `PUBLISHED` and is performed by an `OperationsManager`. Three preconditions hold: `assigned_technician_id` must be non-null (else `ERR_TECH_REQUIRED`); the assigned technician's `active` flag must be true (else `ERR_TECH_INACTIVE`); and `committed_visit_count` must be at least 1 (else `ERR_EMPTY_ROUTE`). Unpublishing reverses the step, moving a route from `PUBLISHED` back to `PLANNED`, but is rejected with `ERR_INVALID_STATE` (HTTP 409) while any visit on the route is `EN_ROUTE` or `ON_SITE`.

On the service date, the assigned `Technician` starts the route, moving it from `PUBLISHED` to `IN_PROGRESS`. Starting requires the acting technician's id to equal `assigned_technician_id` (else `ERR_ROUTE_TECH_MISMATCH`) and the current logical date to equal `service_date` (else `ERR_ROUTE_WRONG_DAY`).

The visit lifecycle then proceeds per visit. The technician departs for a visit, transitioning it from `SCHEDULED` to `EN_ROUTE`; departure requires the visit's `service_route_id` to be non-null (else `ERR_ROUTE_NOT_ASSIGNED`), the route to be `IN_PROGRESS` (else `ERR_ROUTE_NOT_IN_PROGRESS`), and the acting technician to match the route's `assigned_technician_id` (else `ERR_ROUTE_TECH_MISMATCH`). At any point before arrival — that is, while the visit is `SCHEDULED` or `EN_ROUTE` — the technician may record the pet-safety acknowledgement, which writes the current logical time to `tech_safety_ack_at`; this step is mandatory whenever the yard's `pet_aggression_flag` is not `NONE`. Arrival moves the visit from `EN_ROUTE` to `ON_SITE` and enforces two checks in order: if the yard's `pet_aggression_flag` is `CAUTION` or `AGGRESSIVE`, `tech_safety_ack_at` must be non-null (else `ERR_PET_SAFETY_ACK_REQUIRED`); and if the flag is `AGGRESSIVE`, the acting technician's `certified_for_aggressive_pets` must be true (else `ERR_TECH_NOT_CERTIFIED_AGGRESSIVE`). Completion moves the visit from `ON_SITE` to `COMPLETED`, stamps `completed_at` with the current logical time, computes `final_visit_charge_cents` via the FINAL per-visit variant, increments the customer's `lifetime_visits_completed` by one, recomputes the customer's `satisfaction_rolling_avg`, and bubbles the parent route from `IN_PROGRESS` to `CLOSED` once every visit on it has reached a terminal state — the same auto-close check runs whenever any visit on an `IN_PROGRESS` route becomes terminal, whether by completion, skip, miss, or cancel. An `OperationsManager` may also close a route manually once every visit on it has reached a terminal state.

Two system transitions operate on visits. The end-of-day sweep, exposed as a test-driving capability, scans `SCHEDULED` visits whose `scheduled_window_end` has passed relative to the current logical time and transitions them to `MISSED`, setting `skip_source` to `OTHER`, `final_visit_charge_cents` to 0, decrementing the route's `committed_visit_count`, recomputing `route_load_factor_bp`, and auto-posting a flat good-will `SATISFACTION_CREDIT` line with `unit_price_cents` 0 onto the `OPEN` invoice covering the visit's `scheduled_date` (creating a new `OPEN` invoice for that calendar month when none exists). The subscription-pause cascade and subscription-cancel cascade both drive affected visits from `SCHEDULED` to `CANCELLED`; a `Customer` or `OperationsManager` may also cancel a single `SCHEDULED` visit directly. Any of these cancel paths decrements the route's committed count and recomputes its load factor.

### 3.6. Vacation Windows and Customer-Initiated Skips

A `VacationWindow` declares a period during which visits on a subscription should be skipped. Either a `Customer` or an `OperationsManager` creates one by supplying `subscription_id`, `start_date`, `end_date`, and a `skip_reason` drawn from exactly `VACATION`, `WEATHER_HOLD`, `CUSTOMER_REQUEST`, or `HOA_DIRECTIVE`. The window must satisfy `start_date` not later than `end_date` and `start_date` not earlier than the current logical date (else `ERR_INVALID_WINDOW`), and it must not overlap — using closed-interval overlap on dates — any other `SCHEDULED` or `APPLIED` window on the same subscription (else `ERR_WINDOW_OVERLAP`). A new window starts in `window_status` `SCHEDULED`.

When the logical clock reaches a window's `start_date`, the vacation-window applier transitions the window from `SCHEDULED` to `APPLIED`, provided the subscription's `status` is `ACTIVE` or `PAUSED` at apply time. The cascade is significant: every visit on the subscription whose `scheduled_date` falls within the closed interval `[start_date, end_date]` and whose status is currently `SCHEDULED` transitions to `SKIPPED` with `skip_source` set to `VACATION`, and each such transition fires the standard visit-skip side effects, including the `VACATION_CREDIT` line posted onto the covering invoice. A `Customer` or `OperationsManager` may cancel a window that has not yet started — that is, while the current logical time is strictly before `start_date`; attempting to cancel at or after the start is rejected with `ERR_WINDOW_ALREADY_STARTED`.

A `Customer` may also skip a single future visit directly; only a visit in `SCHEDULED` status may be skipped (any other status is rejected with `ERR_INVALID_STATE`). The skip is permitted only when the visit's `scheduled_date` is strictly after today (else `ERR_TOO_LATE_TO_SKIP`) and the visit is not on a route that is currently `IN_PROGRESS` (else `ERR_ROUTE_LOCKED`). On a successful skip, `skip_source` is set to `CUSTOMER_REQUEST`, `final_visit_charge_cents` is set to 0, the route's `committed_visit_count` is decremented and `route_load_factor_bp` recomputed, and — if the subscription's `status` was `ACTIVE` at skip time — a vacation-skip credit is posted onto the `OPEN` invoice covering the skipped date.

The vacation-skip credit calculation has pinned rounding. The credit per visit is the subscription's `monthly_fee_cents_snapshot` divided by the average visits per month for the plan's `visit_frequency` (the same 4.33 / 2.17 / 8.67 / 30 mapping as the per-visit charge), rounded half-up to whole cents per line — this per-line rounding happens before any aggregation, never as a sum-then-round. Each skipped visit generates `VACATION_CREDIT` lines with `quantity` 1 and `unit_price_cents` equal to the negated per-visit credit, split across invoices when the cap described below binds (one line per invoice touched). The waterfall then allocates the credit: if an `OPEN` invoice covers the skipped visit's `scheduled_date`, the credit posts there; otherwise, if no invoice at all covers that date, a new `OPEN` invoice is created for the calendar month containing it and the credit posts to it; if a covering invoice exists but is no longer `OPEN` (for example already `FINALIZED`), the credit posts to the next `OPEN` invoice — the one with the earliest `billing_period_start` after the covering invoice's period start — creating one spanning from the covering invoice's `billing_period_end` to the next month boundary when none exists. On an invoice that already carries charge lines, each posted credit is capped so the invoice's running line-item sum never drops below zero; on an invoice carrying no charge lines the credit posts in full. Any remainder rolls forward to the next `OPEN` invoice under the same rule.

### 3.7. Invoicing and Credits

A `BillingAdmin` opens an invoice for a customer by supplying `customer_id`, `billing_period_start` (inclusive, UTC midnight), and `billing_period_end` (exclusive, UTC midnight). The new `Invoice` starts in `invoice_status` `OPEN`, with `subtotal_cents`, `credits_applied_cents`, and `total_due_cents` initially zero and `finalized_at` null. Line items accrue onto the open invoice as the period progresses: each completed visit generates a `VISIT_CHARGE` line whose unit price is the base per-visit amount (the amortized monthly fee, without add-ons), each `ACTIVE` add-on applied to a completed visit generates an `ADDON_CHARGE` line with `applied_addon_id` set and the add-on's full `price_cents_per_visit` as unit price (the SANITIZE+DEODORIZE bundle discount applies only to the visit's charge fields, never to invoice lines), each vacation-applied or customer-initiated skip generates `VACATION_CREDIT` lines per the waterfall of §3.6, each invoice-dispute resolution with a positive credit generates a `SATISFACTION_CREDIT` line on the next `OPEN` invoice, each missed-visit sweep generates a zero-amount `SATISFACTION_CREDIT` line, and the reconcile-at-finalize step adds the `SUBSCRIPTION_FEE_PRORATED` line. Visit-charge, add-on-charge, and missed-visit credit lines post to the `OPEN` invoice covering the visit's `scheduled_date`, creating a new `OPEN` invoice for that calendar month when none covers it. Free-form `ADJUSTMENT` lines are also permitted. Each `InvoiceLineItem` carries an `invoice_id` referencing its parent invoice, a `line_type` drawn from exactly `SUBSCRIPTION_FEE_PRORATED`, `VISIT_CHARGE`, `ADDON_CHARGE`, `VACATION_CREDIT`, `SATISFACTION_CREDIT`, or `ADJUSTMENT`, a `description`, an integer `quantity` of at least 1, a `unit_price_cents` (negative for credits), and a computed `line_total_cents` equal to the quantity multiplied by the unit price. The `visit_id` references the originating visit for visit-derived lines (visit charges, add-on charges, vacation credits, and missed-visit good-will credits) and is null for non-visit lines; several lines on one invoice may share the same `visit_id`. A visit's `invoiced_at` timestamp is stamped when its completion charge lines are posted and remains null until then — skip- and sweep-generated credit lines do not stamp it. As noted earlier, `InvoiceLineItem` is the one entity without `updated_at` and `version`.

Finalizing an invoice moves it from `OPEN` to `FINALIZED` and is performed by a `BillingAdmin`. The request must carry `expected_invoice_version`; a mismatch against the invoice's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Finalization is further blocked while `billing_period_end` is still in the future relative to the logical clock (else `ERR_PERIOD_NOT_CLOSED`). On success, the finalize step computes `subtotal_cents` as the sum of every line item's `line_total_cents`, then `credits_applied_cents` as the smaller of the customer's current `credit_balance_cents` and the subtotal, then `total_due_cents` as the subtotal minus the credits applied (floored at zero by construction, since credits applied never exceed the subtotal). The customer's `credit_balance_cents` is reduced by `credits_applied_cents`, and `finalized_at` is stamped with the current logical time. Finalizing increments the invoice's `version` by one. The `SUBSCRIPTION_FEE_PRORATED` lines are generated at the start of the finalize step: one per `ACTIVE` subscription of the customer that has a `started_on`, with `quantity` equal to the count of days from the later of `billing_period_start` and `started_on` (compared by calendar date) through `billing_period_end` exclusive — subscriptions with no active days in the period are skipped — and `unit_price_cents` equal to the reconciled monthly fee divided by the period's length in days, rounded half-up per day.

A finalized invoice may be paid. The `BillingAdmin` records payment by supplying `amount_cents`, which must exactly equal `total_due_cents` — no overpayment, no underpayment — else `ERR_PAYMENT_AMOUNT_MISMATCH`. A successful payment moves the invoice to `PAID`. Alternatively, the `Customer` may dispute a finalized invoice by supplying a `reason`; the invoice moves to `DISPUTED`. Dispute resolution is performed by a `BillingAdmin`, who supplies a `resolution_credit_cents` that must be at least 0 and at most 100000 (else `ERR_CREDIT_OUT_OF_RANGE`). If the resolution credit is positive, a `SATISFACTION_CREDIT` line is posted to the next `OPEN` invoice — the one with the earliest `billing_period_start` after the disputed invoice's period start — creating one spanning the disputed invoice's `billing_period_end` through the next month boundary if none exists, and the customer's `credit_balance_cents` is increased by the resolution amount; the invoice then moves to `RESOLVED`.

### 3.8. Satisfaction Reports and Service Recovery

After a visit, the `Customer` may file a satisfaction report by supplying `customer_id`, the `visit_id` the report refers to, a `rating` between 1 and 5 inclusive, and an `issue_category` drawn from exactly `MISSED_SPOT`, `LATE_ARRIVAL`, `GATE_ISSUE`, `PET_SAFETY`, `BILLING`, or `OTHER`. The referenced visit must belong to the filing customer (otherwise `ERR_UNAUTHORIZED`); any existing visit may be referenced regardless of its status. A `rating` outside 1–5 is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Filing a report immediately recomputes the customer's `satisfaction_rolling_avg`. A new report starts in `report_status` `SUBMITTED` with `resolution_credit_cents` and `resolved_at` unset.

An `OperationsManager` picks up a submitted report by moving it from `SUBMITTED` to `UNDER_REVIEW`. From `UNDER_REVIEW`, two paths exist. The manager may escalate the report, moving it to `ESCALATED`, which hands ownership to finance. Or the manager may resolve the report directly by supplying a `resolution_credit_cents` between 0 and 100000 inclusive (else `ERR_CREDIT_OUT_OF_RANGE`); resolution stamps `resolved_at` with the current logical time, writes the credit onto the report, adds the credit to the customer's `credit_balance_cents`, and recomputes the customer's `satisfaction_rolling_avg`. An escalated report is resolved by a `BillingAdmin` rather than an `OperationsManager`, with the same credit range, the same credit posting to `credit_balance_cents`, and the same rolling-average recompute. The resolve action is valid only for the matching pair — `UNDER_REVIEW` with `OperationsManager`, or `ESCALATED` with `BillingAdmin`; any other combination of report status and role is rejected with `ERR_INVALID_STATE` (HTTP 409).

The rolling satisfaction score uses exponential decay by report age. For each report on the customer, the weight is 0.9 raised to the power of the number of whole days since the report's `created_at` — step decay per day, not continuous. The score is the sum of each `rating` multiplied by its weight, divided by the sum of the weights, and rounded half-up to two decimal places at the final division only. One special rule applies: a report that has been `RESOLVED` contributes as if its rating were 5.0, treating the resolution as a fresh perfect interaction. When the customer has no reports at all, `satisfaction_rolling_avg` is null.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Successful resource creation returns HTTP 201; all other successful operations (single reads, list reads, state transitions, updates) return HTTP 200. Error responses use the standard error envelope with an appropriate 4xx status code.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|---------------------|
| POST | /api/customers | Register a new customer | OperationsManager |
| GET | /api/customers/{id} | Fetch single customer | OperationsManager, BillingAdmin, Customer |
| GET | /api/customers | List customers | OperationsManager, BillingAdmin |
| POST | /api/yards | Add a serviceable yard for a customer | OperationsManager, Customer |
| GET | /api/yards/{id} | Fetch yard | OperationsManager, Customer, Technician |
| GET | /api/yards | List yards | OperationsManager, Customer, Technician |
| PUT | /api/yards/{id} | Update yard size/pet count and related fields | OperationsManager, Customer |
| POST | /api/yards/{id}/access-profile | Create the 1:1 access profile for a yard | OperationsManager, Customer |
| GET | /api/yards/{id}/access-profile | Get the yard's access profile (array of 0 or 1) | OperationsManager, Customer, Technician |
| GET | /api/property-access-profiles | Filtered list of access profiles | OperationsManager, Customer, Technician |
| POST | /api/property-access-profiles/{id}/verify | Mark profile VERIFIED | OperationsManager |
| POST | /api/property-access-profiles/{id}/suspend | Suspend access (gate broken, pet incident) | OperationsManager |
| POST | /api/property-access-profiles/{id}/require-reverification | Force profile back to VERIFICATION_PENDING | OperationsManager |
| POST | /api/subscription-plans | Define a new plan | OperationsManager |
| GET | /api/subscription-plans | List plans | OperationsManager, Customer, BillingAdmin |
| GET | /api/subscription-plans/{id} | Get one plan | OperationsManager, Customer, BillingAdmin |
| POST | /api/service-addons | Define an addon (SANITIZE / DEODORIZE) | OperationsManager |
| GET | /api/service-addons | List addons | OperationsManager, Customer, BillingAdmin, Technician |
| POST | /api/subscriptions | Create subscription (status DRAFT) | OperationsManager, Customer |
| GET | /api/subscriptions/{id} | Get subscription | OperationsManager, Customer, BillingAdmin |
| GET | /api/subscriptions | List subscriptions | OperationsManager, Customer, BillingAdmin |
| POST | /api/subscriptions/{id}/activate | Activate a draft subscription | Customer |
| POST | /api/subscriptions/{id}/pause | Pause an active subscription | Customer |
| POST | /api/subscriptions/{id}/resume | Resume a paused subscription | Customer |
| POST | /api/subscriptions/{id}/cancel | Cancel a subscription | Customer |
| POST | /api/subscriptions/{id}/plan-change | Stage a plan change (OCC-guarded) | Customer |
| POST | /api/technicians | Onboard a technician | OperationsManager |
| GET | /api/technicians/{id} | Get a technician | OperationsManager, Technician |
| POST | /api/service-routes | Plan a route for a service date | OperationsManager |
| GET | /api/service-routes/{id} | Get route | OperationsManager, Technician, BillingAdmin |
| GET | /api/service-routes | List routes | OperationsManager, Technician, BillingAdmin |
| GET | /api/service-routes/{id}/visits | Visits assigned to a route | OperationsManager, Technician, BillingAdmin |
| POST | /api/service-routes/{id}/publish | Publish a planned route | OperationsManager |
| POST | /api/service-routes/{id}/unpublish | Return a published route to planned | OperationsManager |
| POST | /api/service-routes/{id}/start | Start a published route on its service date | Technician |
| POST | /api/service-routes/{id}/close | Manually close an in-progress route | OperationsManager |
| POST | /api/visits | Schedule a new visit on a subscription | OperationsManager, Customer |
| GET | /api/visits/{id} | Get visit | OperationsManager, Customer, Technician, BillingAdmin |
| GET | /api/visits | List visits | OperationsManager, Customer, Technician, BillingAdmin |
| POST | /api/visits/{id}/assign-route | Assign or reassign a visit's route | OperationsManager |
| POST | /api/visits/{id}/depart | Mark the technician as departed for the visit | Technician |
| POST | /api/visits/{id}/ack-safety | Record the pet-safety acknowledgement | Technician |
| POST | /api/visits/{id}/arrive | Mark arrival on-site | Technician |
| POST | /api/visits/{id}/complete | Complete the visit | Technician |
| POST | /api/visits/{id}/skip | Customer-initiated skip of a future visit | Customer |
| POST | /api/visits/{id}/cancel | Cancel a scheduled visit | Customer, OperationsManager |
| POST | /api/vacation-windows | Schedule a vacation/skip window | Customer, OperationsManager |
| GET | /api/vacation-windows/{id} | Get vacation window | Customer, OperationsManager |
| GET | /api/subscriptions/{id}/vacation-windows | List vacation windows for a subscription | Customer, OperationsManager |
| POST | /api/vacation-windows/{id}/cancel | Cancel a future vacation window | Customer, OperationsManager |
| POST | /api/invoices | Open a new billing invoice for a customer and period | BillingAdmin |
| GET | /api/invoices/{id} | Get invoice | BillingAdmin, Customer |
| GET | /api/invoices | List invoices | BillingAdmin, Customer |
| GET | /api/invoices/{id}/line-items | Line items on an invoice | BillingAdmin, Customer |
| GET | /api/invoice-line-items | Filtered list of invoice line items across invoices | BillingAdmin, Customer, OperationsManager |
| GET | /api/invoice-line-items/{id} | Get a single invoice line item by id | BillingAdmin, Customer, OperationsManager |
| POST | /api/invoices/{id}/finalize | Finalize an open invoice (OCC-guarded) | BillingAdmin |
| POST | /api/invoices/{id}/record-payment | Record payment against a finalized invoice | BillingAdmin |
| POST | /api/invoices/{id}/dispute | Customer disputes a finalized invoice | Customer |
| POST | /api/invoices/{id}/resolve-dispute | Resolve a disputed invoice | BillingAdmin |
| POST | /api/satisfaction-reports | Customer files a satisfaction report | Customer |
| GET | /api/satisfaction-reports/{id} | Get a report | OperationsManager, BillingAdmin, Customer |
| GET | /api/satisfaction-reports | List reports | OperationsManager, BillingAdmin, Customer |
| POST | /api/satisfaction-reports/{id}/begin-review | Begin review on a submitted report | OperationsManager |
| POST | /api/satisfaction-reports/{id}/escalate | Escalate a report under review | OperationsManager |
| POST | /api/satisfaction-reports/{id}/resolve | Resolve a report and credit the customer | OperationsManager, BillingAdmin |
| POST | /api/_clock/set_current_utc | Advance the logical clock | OperationsManager |
| POST | /api/_system/vacation-window-applier/run | Synchronously apply due vacation windows | OperationsManager |
| POST | /api/_system/end-of-day-sweep/run | Synchronously run the missed-visit sweep | OperationsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_ACCESS_NOT_VERIFIED | 422 |
| ERR_GATE_CODE_REQUIRED | 422 |
| ERR_PET_SAFETY_ACK_REQUIRED | 422 |
| ERR_TECH_NOT_CERTIFIED_AGGRESSIVE | 422 |
| ERR_HOA_CODE_REQUIRED | 422 |
| ERR_PLAN_SCOPE_MISMATCH | 422 |
| ERR_PLAN_RETIRED | 422 |
| ERR_YARD_OWNERSHIP_MISMATCH | 422 |
| ERR_INVALID_WINDOW | 422 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_INVALID_TIME_WINDOW | 422 |
| ERR_VISIT_WINDOW_CONFLICT | 409 |
| ERR_ROUTE_AT_CAPACITY | 409 |
| ERR_ROUTE_NOT_ASSIGNED | 422 |
| ERR_ROUTE_NOT_IN_PROGRESS | 409 |
| ERR_ROUTE_TECH_MISMATCH | 403 |
| ERR_ROUTE_WRONG_DAY | 409 |
| ERR_ROUTE_LOCKED | 409 |
| ERR_TECH_REQUIRED | 422 |
| ERR_TECH_INACTIVE | 422 |
| ERR_EMPTY_ROUTE | 422 |
| ERR_TOO_LATE_TO_SKIP | 409 |
| ERR_VISIT_IN_FLIGHT | 409 |
| ERR_WINDOW_ALREADY_STARTED | 409 |
| ERR_PERIOD_NOT_CLOSED | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_CREDIT_OUT_OF_RANGE | 422 |
| ERR_SUBSCRIPTION_NOT_SERVICEABLE | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
