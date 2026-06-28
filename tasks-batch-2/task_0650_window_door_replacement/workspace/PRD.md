# Window Door Replacement API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Window & Door Replacement API, a back-office platform that orchestrates the full residential remodeling journey practiced by premium replacement-window companies. A typical engagement begins when a sales representative books an in-home consultation to measure and configure each window or door opening, continues through an itemized quote that incorporates volume discounts, energy-tax-credit estimates, and optional financing, and proceeds — once the homeowner commits — into custom manufacturing, crew scheduling, permitting, municipal inspection, and finally warranty service and customer referrals.

The platform must reconcile two distinct kinds of complexity. First, it is a workflow-orchestration system: a project advances through many interdependent stages, and a single act such as accepting a quote ripples outward into production, scheduling, supersession, and referral settlement. Second, it is a pricing engine: per-opening list prices, tiered discounts, the federal 25C Energy Efficient Home Improvement Credit, manufacturing lead times, amortized financing payments, service charges, and referral rewards must all be computed deterministically and to the cent. Because manufacturing and inspection deadlines are time-driven, the system relies on an explicit logical clock rather than wall-clock time, allowing every time-dependent rule to be exercised reproducibly.

Throughout, the API enforces role separation among the people who touch a project — the sales side that consults and quotes, the operations side that builds, schedules, permits, and decides financing, the service side that handles callbacks, and the homeowner who commits to the work — while guaranteeing immediate, internally consistent state across the entire project tree.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header — or carrying an empty value for either — is rejected with `ERR_UNAUTHENTICATED`. Even the logical-clock test-driving endpoint requires these headers despite being an administrative utility. Once a caller is authenticated, the system checks whether the supplied `X-User-Role` is permitted to perform the requested operation; if it is not, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles: `Homeowner`, `SalesConsultant`, `OperationsCoordinator`, `ServiceTech`, and `PlatformAdmin`. A `SalesConsultant` runs consultations and measures, configures openings, drafts and sends quotes, and creates referrals. An `OperationsCoordinator` owns production, install scheduling, permits, financing decisions, and project cancellation. A `ServiceTech` handles warranty callbacks by dispatching, resolving, and closing service tickets. A `Homeowner` is the paying customer who accepts or rejects quotes, submits financing applications, opens callbacks, and reopens service tickets. A `PlatformAdmin` is an operator superset that seeds reference data, drives the logical clock, and reads everything.

The `Homeowner` role is entity-backed: when `X-User-Role` is `Homeowner`, the `X-User-ID` is the `id` of the acting `Homeowner` record, and any ownership check on a resource that descends from a project compares that project's `homeowner_id` to `X-User-ID`. Concretely, when a homeowner accepts a quote, rejects a quote, or reopens a service ticket, the system verifies that the homeowner owns the underlying project; if they do not, the request is rejected with `ERR_NOT_PROJECT_OWNER`. The other four roles are opaque operator identifiers not tied to any persisted entity. When `X-User-Role` is `SalesConsultant`, `OperationsCoordinator`, `ServiceTech`, or `PlatformAdmin`, the `X-User-ID` is an opaque operator identifier that the server does not compare to any entity's `id`; it may, however, record it — for example, a consultation persists the acting consultant's identifier as `consultant_id` for audit, and that field is never resolved as a foreign key to any stored entity.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0; a negative offset is invalid. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`.

Unless stated otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted resource in the system carries a server-minted `id` formatted as a bare UUID with no type prefix; the identifier is used only for addressing and never participates in business decisions. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created.

All resources in this system additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, and the `version` field starts at 1 and increases by exactly 1 on every mutation. Because the platform has no immutable-after-creation entities, both fields are present on every resource, including the `Homeowner`, `Project`, `Consultation`, `Opening`, `Quote`, `FinancingApplication`, `ManufactureOrder`, `Crew`, `InstallJob`, `Permit`, `ServiceTicket`, and `Referral`.

### 2.5. Hierarchical Consistency and Compound Project State

Resources are organized as a tree rooted at the `Project`. A consultation hangs off a project, an opening hangs off a consultation, and quotes, financing applications, manufacture orders, install jobs, permits, and service tickets hang off the project (financing applications hang off a quote). A `Project`'s `status` is never set directly by a client; it is a compound value derived from the progress of its children, and the server recomputes it whenever a child stage advances.

When a server-driven recomputation or a cascade alters a resource, that mutation independently refreshes the resource's `updated_at` and increments its `version` — this applies to parent records touched only by cascade just as it applies to records changed by a direct request. For example, when a project's status is recomputed as a side effect of a child transition, the project's `updated_at` and `version` advance even though no request named the project directly. The same holds for the `Quote` and `ManufactureOrder` and `InstallJob` records whose `updated_at` is refreshed on cascaded side effects.

### 2.6. Nested Resource Retrieval and Path Validation

Many endpoints address a resource nested beneath a project, and some nest two levels deep (for instance, a financing application beneath a quote beneath a project). For any such request the system validates each path identifier in strict left-to-right order, rejecting the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A request naming a quote under a project that does not exist fails on the project before the quote is ever consulted. Existence of every path-referenced resource is checked ahead of business rules.

### 2.7. Precision, Rounding, and Monetary Representation

All monetary amounts are stored and returned as integer cents. Where a rule multiplies an amount by a rate and the product is not a whole number of cents, the result is rounded half-up to the nearest whole cent. Each rounding boundary is called out explicitly in the calculation that requires it, and the order of rounding relative to summation matters: per-opening prices are each rounded once at the moment they are computed, and downstream totals sum those already-rounded values rather than re-rounding a running sum. Lead times and other day counts are whole integers of logical days.

### 2.8. Optimistic Concurrency Control on Quote Acceptance

Accepting a quote is the single operation guarded by optimistic concurrency control. The acceptance request must carry an `expected_quote_version` field, and that field is mandatory for this operation; it expresses the `version` of the target quote that the client last observed. A `SENT` quote's `version` advances on any prior mutation — a re-send refresh, a financing decision recorded against it, or its own acceptance. If the supplied `expected_quote_version` does not equal the quote's current `version` at the moment of acceptance, the client is acting on a stale view of the quote, and the acceptance is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412) rather than committing terms the client never saw. No other endpoint accepts or requires a version field; only quote acceptance performs this check.

### 2.9. The Logical Clock

Time in this system is governed by a logical clock rather than the host's wall clock. At server startup the clock reads exactly `2026-04-01T00:00:00Z`, and until it is explicitly set it holds that default and never falls back to real time. An administrative test-driving capability advances the clock to a supplied instant carried in the `to_iso8601` field, an explicit ISO 8601 UTC value. Advancing the clock — like reading a project or a quote — is also a moment at which the system lazily expires any quote that has passed its expiry instant. Every time-dependent rule in the platform (quote expiry, manufacturing readiness, install windows, inspection deadlines, and the warranty window) is measured against this logical clock.

### 2.10. Permit Jurisdictions and Energy Standards

Each project is pinned at creation to a permit jurisdiction, captured in `jurisdiction_code`, derived from the homeowner's `property_zip`: a ZIP whose first digit is `9` maps to `WEST_STRICT`; a first digit of `0` or `1` maps to `NORTHEAST_STD`; any other first digit maps to `CENTRAL_LIGHT`. The jurisdiction determines how long after permit approval an inspection must occur — 7 logical days for `WEST_STRICT`, 14 for `NORTHEAST_STD`, and 30 for `CENTRAL_LIGHT`. Energy qualification follows the ENERGY STAR standard: an opening is energy-qualified only when its `u_factor` is at most 0.30, and that qualification determines whether the opening's price contributes to the 25C credit.

## 3. Business Logic & Workflows

### 3.1. Onboarding, Projects, and the Compound Lifecycle

Engagements start with a `Homeowner`, registered with a `full_name`, an `email` that must be unique across all homeowners, and a `property_zip`. A homeowner may optionally declare an `agi_band` — one of `LOW`, `STANDARD`, or `HIGH` — which defaults to `STANDARD` when omitted and later governs both financing rates and the binding energy-credit figure. A homeowner's `referral_credit_cents` is a derived total: it is the sum of `reward_amount_cents` across every `SETTLED` referral on which this homeowner is the referrer, and it is recomputed whenever one of their referrals settles; it begins at 0. Fetching a homeowner returns that computed credit alongside the stored fields.

A `Project` is opened for a homeowner by supplying the `homeowner_id`. At creation the system reads the owning homeowner's `property_zip`, derives and pins `jurisdiction_code` as described in §2.10, and sets the project's `status` to `LEAD`. The project's `accepted_quote_id` — the foreign key to the one quote that ultimately puts the project under contract — remains null until a quote is accepted. Project status is a compound aggregate that the system advances automatically as children progress: the first consultation moves a project from `LEAD` to `CONSULTING`; the first quote that reaches `SENT` advances it to `QUOTING`; an accepted quote advances it to `CONTRACTED`; a manufacture order reaching its build phase advances it to `IN_PRODUCTION`; an install job departing advances it to `INSTALLING`; that install job completing advances it to `INSPECTION`; and a passed inspection advances it to `COMPLETED`. The valid project states are `LEAD`, `CONSULTING`, `QUOTING`, `CONTRACTED`, `IN_PRODUCTION`, `INSTALLING`, `INSPECTION`, `COMPLETED`, and `CANCELLED`.

A project may be cancelled by an `OperationsCoordinator`, but only while it is in one of the states `LEAD`, `CONSULTING`, `QUOTING`, `CONTRACTED`, or `IN_PRODUCTION`, and only if no install job on the project has yet reached `COMPLETED`; otherwise the cancellation is refused as an invalid state with `ERR_INVALID_STATE`. Cancellation runs a conditional cascade that touches only non-terminal children: the project moves to `CANCELLED` (hop 1); every non-terminal manufacture order — any in `QUEUED` or `IN_BUILD` — is cancelled (hop 2); every `SCHEDULED` install job is cancelled and the crew-day capacity it consumed is released (hop 3); and every `PENDING` referral whose referred project is this project is voided to `VOID` (hop 4). When a project is read, the system also lazily evaluates quote expiry, flipping any `SENT` quote now past its expiry to `EXPIRED`.

### 3.2. Consultations and Opening Configuration

A `SalesConsultant` books an in-home measure visit by creating a `Consultation` on a project, supplying the `project_id` of the project being scoped, the `consultant_id` of the operator running the visit, and a `scheduled_at` instant for the booking. The consultation opens in `BOOKED` status, its `total_opening_count` starts at 0, and if it is the first consultation on the project the project advances from `LEAD` to `CONSULTING`. A consultation's lifecycle states are `BOOKED`, `MEASURED`, and `CANCELLED`. A `SalesConsultant` may cancel a consultation only while it is `BOOKED`, which sets it to `CANCELLED` and prompts a recomputation of the parent project's status; cancelling anything not in `BOOKED` is rejected with `ERR_INVALID_STATE`.

During the visit, the consultant records each window or door as an `Opening` against the consultation. Creating an opening requires the `consultation_id`, the `product_type` — one of `DOUBLE_HUNG`, `CASEMENT`, `PICTURE`, `SLIDING_PATIO_DOOR`, or `ENTRY_DOOR` — the measured rough-opening `width_in` and `height_in` (each of which must be strictly greater than 0), and a `glass_package` of `STANDARD`, `LOWE_DUAL`, or `LOWE_TRIPLE`. Each created opening bumps the parent consultation's `total_opening_count` by one. From the glass package the system derives the opening's `u_factor`: `STANDARD` yields 0.40, `LOWE_DUAL` yields 0.27, and `LOWE_TRIPLE` yields 0.20, where a lower figure is better. The opening's `energy_qualified` flag is true exactly when its `u_factor` is at most 0.30, and it defaults to false; consequently `STANDARD` openings are not energy-qualified while both Low-E packages are. The consultant may later revise an opening's `glass_package`, which recomputes `u_factor`, `energy_qualified`, and the per-opening price.

The per-opening list price, `unit_price_cents`, is computed both when an opening is created and whenever its glass package changes. First, the opening's area in square feet is its `width_in` multiplied by its `height_in`, divided by 144, kept exact and not yet rounded. A base rate per square foot is selected by product type — 4,200 cents for `DOUBLE_HUNG`, 4,800 for `CASEMENT`, 3,600 for `PICTURE`, 5,200 for `SLIDING_PATIO_DOOR`, and 6,000 for `ENTRY_DOOR`. A glass uplift per square foot is added on top, selected by glass package — 0 cents for `STANDARD`, 900 for `LOWE_DUAL`, and 1,800 for `LOWE_TRIPLE`. The raw price is the area multiplied by the sum of the base rate and the glass uplift; this raw amount is then rounded half-up to whole cents exactly once, per opening, to produce `unit_price_cents`.

A consultant marks the measure complete to advance the consultation from `BOOKED` to `MEASURED`. This transition requires that the consultation is currently `BOOKED` and that at least one opening has been added — that is, `total_opening_count` is one or more. An attempt to complete a measure that has captured zero openings is rejected with `ERR_NO_OPENINGS`; an empty measure can never be marked measured. Completing the measure recomputes the parent project's compound status.

### 3.3. Quoting, Discounts, and the 25C Energy Credit

A `SalesConsultant` drafts a `Quote` against a measured consultation by supplying the `project_id` and the `consultation_id` whose openings the quote will price. A quote opens in `DRAFT`. To re-quote after a rejection, the consultant may pass an optional `supersede_quote_id` referencing a previously rejected quote; this creates a brand-new `DRAFT` quote as a revision while leaving the prior `REJECTED` quote untouched, allowing sales to iterate without losing history. The full set of quote states is `DRAFT`, `SENT`, `ACCEPTED`, `REJECTED`, `EXPIRED`, and `SUPERSEDED`.

Sending a quote advances it from `DRAFT` to `SENT`, but only if the quote is currently `DRAFT` and its linked consultation has reached `MEASURED`; sending against a consultation that is not measured is rejected with `ERR_CONSULTATION_NOT_MEASURED`. Sending pins the quote's pricing and starts the expiry clock: the system computes `openings_subtotal_cents`, `discount_tier`, and `estimate_total_cents`, computes the provisional `provisional_rebate_cents`, sets `expires_at` to the current logical clock plus 30 logical days, and advances the parent project to `QUOTING` (the first such send is what moves the project out of `CONSULTING`).

The estimate total is built in a pinned order. The `openings_subtotal_cents` is the sum of `unit_price_cents` over every opening on the quote's measured consultation — a sum of values that were each already rounded once at opening time, never a re-rounded running total. The `discount_tier` is then read off that subtotal: a subtotal below 2,000,000 cents earns `NONE` at 0 percent; a subtotal from 2,000,000 cents up to but not including 4,000,000 cents earns `TIER1` at 5 percent; and a subtotal of 4,000,000 cents or more earns `TIER2` at 10 percent. The discount in cents is the subtotal multiplied by the tier's percentage, rounded half-up exactly once. An install fee is a flat 35,000 cents plus 1,500 cents for each opening, using the consultation's `total_opening_count`. Finally, `estimate_total_cents` is the subtotal minus the rounded discount plus the install fee; all terms other than the discount are already whole cents.

The provisional 25C rebate shown at send time is the optimistic ceiling of the federal Energy Efficient Home Improvement Credit. The system considers only energy-qualified openings — those whose `energy_qualified` is true — and splits them by type: windows are `DOUBLE_HUNG`, `CASEMENT`, and `PICTURE`, while doors are `ENTRY_DOOR` and `SLIDING_PATIO_DOOR`. The window credit is 30 percent of the summed `unit_price_cents` of qualified windows, rounded half-up to whole cents, then capped so it cannot exceed 60,000 cents (the $600 aggregate annual exterior-window cap). The door credit is 30 percent of the summed `unit_price_cents` of qualified doors, rounded half-up to whole cents, then capped so it cannot exceed 50,000 cents (the $500 total-doors cap). Each 30-percent multiply is rounded before its cap is applied. The provisional figure, stored as `provisional_rebate_cents`, sums the capped window credit and the capped door credit over all energy-qualified openings present at send time, regardless of the homeowner's AGI band.

### 3.4. Acceptance, the Production Cascade, and Quote Closure

A `Homeowner` who owns the project accepts a `SENT` quote, and acceptance is the system's central branch point. The accept request must carry `expected_quote_version`. The transition requires that the quote is `SENT`, that the current logical clock is strictly before the quote's `expires_at`, that `expected_quote_version` equals the quote's current `version`, and that no other quote on the same project is already `ACCEPTED`. These guards each have a distinct rejection: a quote that is not `SENT` fails with `ERR_INVALID_STATE`; a stale version fails with `ERR_STALE_QUOTE_VERSION`; accepting at or after the expiry instant fails with `ERR_QUOTE_EXPIRED`; and a second acceptance on an already-contracted project fails with `ERR_PROJECT_ALREADY_CONTRACTED`.

A successful acceptance increments the quote's `version` by one, moves the quote to `ACCEPTED`, and then fans out a four-hop cascade. Hop one sets the project's `accepted_quote_id` to this quote's `id` and recomputes the project's status to `CONTRACTED`. Hop two auto-creates a `ManufactureOrder` in `QUEUED` status, recording its `project_id` and `quote_id` and computing its `lead_time_days` and `ready_at`. Hop three sets every other `SENT` quote on the same project to `SUPERSEDED`. Hop four settles any `PENDING` referral whose referred project is this project: that referral moves to `SETTLED`, its `reward_amount_cents` is computed, and the referring homeowner's `referral_credit_cents` is recomputed. The reverse fork is rejection: a `Homeowner` rejects a `SENT` quote, moving it to `REJECTED`, cancelling any `SUBMITTED` financing application on that quote (its status becomes `CANCELLED`), and recomputing the parent project's status — back to `QUOTING` if other live quotes exist on the project, otherwise back to `CONSULTING`.

Two quote transitions are entirely system-driven. A `SENT` quote whose `expires_at` has been reached or passed transitions to `EXPIRED`; this is evaluated lazily whenever the quote or its project is read and whenever the logical clock is set. Separately, when a sibling quote on the same project is accepted, each other `SENT` quote on that project transitions to `SUPERSEDED`. A `REJECTED` quote is the entry point for the revision loop described above: a new `DRAFT` is created from it, and the rejected quote itself is left unchanged.

### 3.5. Financing

Either a `Homeowner` or a `SalesConsultant` may submit a `FinancingApplication` against a quote, supplying the `quote_id`, the `requested_amount_cents` to finance (which must be greater than 0), and a `term_months` value of 12, 24, 36, or 60. The application opens in `SUBMITTED`. Its lifecycle states are `SUBMITTED`, `APPROVED`, `DECLINED`, and `CANCELLED`. An `OperationsCoordinator` decides the application by submitting a `decision`. A decision to decline simply moves a `SUBMITTED` application to `DECLINED`. A decision to approve requires that the application is `SUBMITTED` and that `requested_amount_cents` is no greater than the linked quote's `estimate_total_cents`; a request to finance more than the quote total is rejected with `ERR_FINANCING_OVER_QUOTE`. As noted in §3.4, a financing application still in `SUBMITTED` is automatically cancelled when its quote is rejected.

On approval the system assigns the `approved_apr_bps` and computes the `monthly_payment_cents`; both remain null until approval. The APR in basis points is looked up by the homeowner's `agi_band` and the requested `term_months`. For the `LOW` band the rates are 0 basis points at 12 months, 0 at 24, 599 at 36, and 899 at 60. For the `STANDARD` band they are 0 at 12 months, 499 at 24, 899 at 36, and 1,299 at 60. For the `HIGH` band they are 299 at 12 months, 799 at 24, 1,199 at 36, and 1,599 at 60. When the looked-up APR is 0 basis points — a promotional zero-interest plan — the monthly payment is the financed principal `requested_amount_cents` divided by the number of months and rounded up to the next whole cent, so that the payments sum to at least the principal. Otherwise the monthly rate is the APR in basis points divided by 10,000 and then by 12, carried at full precision; the amortization factor is that monthly rate multiplied by one-plus-the-monthly-rate raised to the number of months, divided by the quantity one-plus-the-monthly-rate raised to the number of months minus one; and the monthly payment is the principal multiplied by that factor, rounded half-up to whole cents exactly once at the end.

### 3.6. Manufacturing and Lead Time

When a quote is accepted, the auto-created `ManufactureOrder` (states `QUEUED`, `IN_BUILD`, `READY`, and `CANCELLED`) immediately receives a computed `lead_time_days` and a derived `ready_at`. The lead time keys off the slowest product among the accepted quote's openings. The base build time in logical days per product type is 28 for `DOUBLE_HUNG`, 35 for `CASEMENT`, 21 for `PICTURE`, 49 for `SLIDING_PATIO_DOOR`, and 42 for `ENTRY_DOOR`; the system takes the maximum of these over all openings on the consultation. If any opening on the order carries the `LOWE_TRIPLE` glass package, a rush surcharge of 14 logical days is added to that maximum; otherwise no surcharge applies. The resulting `lead_time_days` is the slowest base time plus any surcharge, and `ready_at` is the manufacture order's creation instant on the logical clock plus that many logical days.

An `OperationsCoordinator` starts the build, moving a `QUEUED` order to `IN_BUILD`. This requires the order to be `QUEUED` and the parent project to be `CONTRACTED`; it advances the project to `IN_PRODUCTION`. The coordinator later marks the order ready, moving it from `IN_BUILD` to `READY`, which requires the order to be `IN_BUILD` and the current logical clock to have reached or passed `ready_at` — that is, the lead time must have elapsed. A manufacture order in `QUEUED` or `IN_BUILD` is also cancelled to `CANCELLED` by the system when its parent project is cancelled.

### 3.7. Crews, Install Scheduling, and Capacity

Install work is performed by a `Crew`, registered by an `OperationsCoordinator` or `PlatformAdmin` with a display `name`, a `home_jurisdiction` of `WEST_STRICT`, `NORTHEAST_STD`, or `CENTRAL_LIGHT`, and a `daily_capacity_openings` value that must be at least 1, capping how many openings the crew can install in one calendar day.

An `OperationsCoordinator` schedules an `InstallJob` on a project by supplying the `project_id`, the `crew_id` of the assigned crew, and a half-open install window defined by `window_start` (inclusive) and `window_end` (exclusive), where `window_end` must be strictly later than `window_start`. The job opens in `SCHEDULED`; its lifecycle states are `SCHEDULED`, `EN_ROUTE`, `COMPLETED`, and `CANCELLED`. At scheduling the system copies the `opening_count` from the accepted quote's consultation `total_opening_count`, and that count is what the job consumes against crew capacity.

Three constraints guard scheduling, each with its own rejection. The assigned crew's `home_jurisdiction` must equal the project's `jurisdiction_code`; a mismatch is rejected with `ERR_CREW_JURISDICTION_MISMATCH`. The new window must not overlap any other non-terminal install job window on the same crew; because windows are half-open, abutment where one window's end equals another's start is allowed, but any true overlap is rejected with `ERR_CREW_WINDOW_CONFLICT`. Finally, across all non-terminal install jobs on that crew that share any calendar day with the new window, the sum of their `opening_count` plus the new job's must not exceed the crew's `daily_capacity_openings`; equality with the capacity is allowed, but exceeding it is rejected with `ERR_CREW_CAPACITY_EXCEEDED`.

The coordinator dispatches a job by departing it, moving a `SCHEDULED` job to `EN_ROUTE`. Departure requires the job to be `SCHEDULED`, the linked manufacture order to be in `READY` (a crew cannot leave before the goods are built), and the current logical clock to have reached or passed `window_start`; departing before the goods are ready is rejected with `ERR_GOODS_NOT_READY`. Departure advances the project to `INSTALLING`. The coordinator completes an `EN_ROUTE` job, moving it to `COMPLETED`, which requires the job to be `EN_ROUTE` and the project to hold an `APPROVED` (or later) permit; completing without an approved permit is rejected with `ERR_PERMIT_NOT_APPROVED`. Completion advances the project to `INSPECTION`. A `SCHEDULED` job may instead be cancelled by the coordinator, which moves it to `CANCELLED` and releases the crew-day capacity it had consumed.

### 3.8. Permits and Inspection

An `OperationsCoordinator` files a `Permit` on a project, supplying the `project_id`; it opens in `FILED`. The permit lifecycle covers `FILED`, `APPROVED`, `INSPECTION_PASSED`, and `INSPECTION_FAILED`. Approving a `FILED` permit moves it to `APPROVED` and sets `inspection_due_at` to the current logical clock plus the jurisdiction's inspection window — 7 logical days for `WEST_STRICT`, 14 for `NORTHEAST_STD`, and 30 for `CENTRAL_LIGHT`; an inspection recorded after that instant is a deadline-miss flag.

The coordinator records an inspection result against an `APPROVED` permit by supplying a `result`, and recording requires that the project has a `COMPLETED` install job, since inspection only follows installation. A passing result moves the permit to `INSPECTION_PASSED` and recomputes the project to `COMPLETED`, which is what unlocks referral creation and service tickets. A failing result moves the permit to `INSPECTION_FAILED`. A failed permit is not terminal: the coordinator may re-approve it, moving it from `INSPECTION_FAILED` back to `APPROVED` and resetting `inspection_due_at` to the current clock plus the jurisdiction window again, ready for a re-inspection.

### 3.9. Warranty Callbacks and Service Charges

Once a project is `COMPLETED`, a `Homeowner`, `ServiceTech`, or `PlatformAdmin` may open a `ServiceTicket` against a specific opening, supplying the `project_id`, the `opening_id` of the opening reported as defective, and a `category` of either `WARRANTY` or `BILLABLE`. A ticket may be opened only on a `COMPLETED` project — opening one on any other project state is rejected with `ERR_PROJECT_NOT_COMPLETED` — and the referenced `opening_id` must belong to that project. The ticket opens in `OPEN`; its lifecycle states are `OPEN`, `DISPATCHED`, `RESOLVED`, `REOPENED`, and `CLOSED`.

A `ServiceTech` dispatches a ticket from either `OPEN` or `REOPENED` to `DISPATCHED`, resolves a `DISPATCHED` ticket to `RESOLVED`, and closes a `RESOLVED` ticket to `CLOSED`. A `Homeowner` who owns the project may reopen a `RESOLVED` ticket, moving it to `REOPENED`, should the fix fail to hold; from there a tech can dispatch it again, forming a repair cycle. Resolving a ticket computes its `charge_cents`. A `WARRANTY` ticket is always billed at 0 cents. A `BILLABLE` ticket carries a base trip charge of 9,500 cents; if it is resolved out of warranty — that is, the current logical clock has reached or passed the instant 730 logical days (two logical years) after the project's `updated_at` at the time the project reached `COMPLETED` — an additional 5,000-cent surcharge is added, making the charge 14,500 cents, otherwise the charge is just the 9,500-cent base.

### 3.10. Referrals and Rewards

A completed engagement can seed new business. A `SalesConsultant` or `PlatformAdmin` creates a `Referral` by supplying the `referrer_project_id` of the existing project whose owner is referring and the `referred_project_id` of the newly generated project; the two are a self-referential link between two projects. Creation requires that the referrer project's status is `COMPLETED` and that the referrer and referred projects are different; a referrer that is not completed, or a referral that names the same project on both sides, is rejected with `ERR_REFERRER_NOT_COMPLETED`. A referral opens in `PENDING`, with states `PENDING`, `SETTLED`, and `VOID`, and a `reward_amount_cents` that starts at 0.

Referral settlement is system-driven and tied to the referred project's progress. When the referred project reaches `CONTRACTED` — that is, a quote on it is accepted — any `PENDING` referral pointing at it transitions to `SETTLED`: the system computes `reward_amount_cents` and recomputes the referring homeowner's `referral_credit_cents`. The reward is 2 percent of the referred project's accepted quote's `estimate_total_cents`, rounded half-up to whole cents, then capped so it cannot exceed 50,000 cents (the $500 reward cap). Conversely, if the referred project is cancelled before it ever reaches `CONTRACTED`, the `PENDING` referral is voided to `VOID` and no reward is paid; this voiding is also one of the hops in the project-cancellation cascade of §3.1.

### 3.11. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the rejection a client receives is deterministic. Authentication comes first: the presence of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`) is checked before role authorization (`ERR_FORBIDDEN_ROLE`). Next the system confirms that every resource named in the path exists, left to right (`ERR_NOT_FOUND`). Then, for a homeowner acting on a project, project ownership is enforced (`ERR_NOT_PROJECT_OWNER`). After that, foreign-key references carried in a request body — such as `homeowner_id`, `consultation_id`, `crew_id`, `opening_id`, and the referrer and referred project identifiers — must resolve to existing resources (`ERR_REFERENCE_NOT_FOUND`). Only then are state and business rules considered: the target resource must be in the correct state for its transition (`ERR_INVALID_STATE`); the optimistic-concurrency check on quote acceptance (`ERR_STALE_QUOTE_VERSION`) follows; and after that come the domain-specific guards — measured-consultation-before-send (`ERR_CONSULTATION_NOT_MEASURED`), at-least-one-opening (`ERR_NO_OPENINGS`), quote-not-expired (`ERR_QUOTE_EXPIRED`), at-most-one-accepted-quote (`ERR_PROJECT_ALREADY_CONTRACTED`), permit-approved-before-completion (`ERR_PERMIT_NOT_APPROVED`), goods-ready-before-departure (`ERR_GOODS_NOT_READY`), crew jurisdiction (`ERR_CREW_JURISDICTION_MISMATCH`), crew window conflict (`ERR_CREW_WINDOW_CONFLICT`), crew capacity (`ERR_CREW_CAPACITY_EXCEEDED`), financing within quote (`ERR_FINANCING_OVER_QUOTE`), referrer-completed (`ERR_REFERRER_NOT_COMPLETED`), and service-ticket-on-completed-project (`ERR_PROJECT_NOT_COMPLETED`). Last of all, generic request-body validation — required fields present and field types, enums, and numeric ranges valid, such as `width_in` greater than 0 and a `term_months` drawn from the allowed set — is applied to create endpoints and reported as `ERR_INVALID_REQUEST`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return a `201 Created` status code; operations that modify or transition an existing resource, including the logical-clock utility, return a `200 OK` status code. List and fetch operations return `200 OK`. All list endpoints accept the `limit` and `offset` pagination query parameters described in §2.3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/homeowners` | Register a homeowner | SalesConsultant, PlatformAdmin |
| GET | `/homeowners/{id}` | Fetch a homeowner including referral credit | SalesConsultant, OperationsCoordinator, ServiceTech, Homeowner, PlatformAdmin |
| POST | `/projects` | Create a project for a homeowner | SalesConsultant, PlatformAdmin |
| GET | `/projects/{id}` | Fetch a project (live compound status; lazy quote expiry) | SalesConsultant, OperationsCoordinator, ServiceTech, Homeowner, PlatformAdmin |
| GET | `/projects` | List projects, filterable by `homeowner_id` or `accepted_quote_id` | SalesConsultant, OperationsCoordinator, ServiceTech, PlatformAdmin |
| POST | `/projects/{id}/cancel` | Cancel a project (cascades to manufacture, install, referrals) | OperationsCoordinator, PlatformAdmin |
| POST | `/projects/{id}/consultations` | Book a consultation/measure visit | SalesConsultant, PlatformAdmin |
| GET | `/projects/{id}/consultations` | List consultations on a project | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/projects/{id}/consultations/{cid}` | Fetch a single consultation | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| POST | `/projects/{id}/consultations/{cid}/complete-measure` | Mark the measure complete | SalesConsultant |
| POST | `/projects/{id}/consultations/{cid}/cancel` | Cancel a booked consultation | SalesConsultant |
| POST | `/projects/{id}/consultations/{cid}/openings` | Add a configured opening | SalesConsultant |
| GET | `/projects/{id}/consultations/{cid}/openings` | List openings on a consultation | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/openings/{id}` | Fetch a single opening | SalesConsultant, OperationsCoordinator, ServiceTech, Homeowner, PlatformAdmin |
| PATCH | `/openings/{id}` | Update an opening's glass package | SalesConsultant |
| POST | `/projects/{id}/quotes` | Create a DRAFT quote (optional revision) | SalesConsultant |
| GET | `/projects/{id}/quotes` | List quotes on a project (lazy expiry) | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/projects/{id}/quotes/{qid}` | Fetch a single quote (lazy expiry) | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| POST | `/projects/{id}/quotes/{qid}/send` | Send a DRAFT quote | SalesConsultant |
| POST | `/projects/{id}/quotes/{qid}/accept` | Accept a SENT quote (OCC) | Homeowner |
| POST | `/projects/{id}/quotes/{qid}/reject` | Reject a SENT quote | Homeowner |
| POST | `/projects/{id}/quotes/{qid}/financing` | Submit a financing application | Homeowner, SalesConsultant |
| GET | `/projects/{id}/quotes/{qid}/financing` | List financing applications on a quote | Homeowner, SalesConsultant, OperationsCoordinator, PlatformAdmin |
| POST | `/projects/{id}/quotes/{qid}/financing/{fid}/decide` | Approve or decline a financing application | OperationsCoordinator |
| GET | `/projects/{id}/manufacture` | List manufacture orders on a project | OperationsCoordinator, SalesConsultant, Homeowner, PlatformAdmin |
| GET | `/projects/{id}/manufacture/{mid}` | Fetch a single manufacture order | OperationsCoordinator, SalesConsultant, Homeowner, PlatformAdmin |
| POST | `/projects/{id}/manufacture/{mid}/start-build` | Move a QUEUED order to IN_BUILD | OperationsCoordinator |
| POST | `/projects/{id}/manufacture/{mid}/mark-ready` | Move an IN_BUILD order to READY | OperationsCoordinator |
| POST | `/crews` | Register an install crew | OperationsCoordinator, PlatformAdmin |
| GET | `/crews/{id}` | Fetch a crew | OperationsCoordinator, SalesConsultant, PlatformAdmin |
| POST | `/projects/{id}/install-jobs` | Schedule an install job | OperationsCoordinator |
| GET | `/projects/{id}/install-jobs` | List install jobs on a project | OperationsCoordinator, SalesConsultant, Homeowner, PlatformAdmin |
| GET | `/install-jobs` | List install jobs filtered by `crew_id` or `project_id` | OperationsCoordinator, PlatformAdmin |
| GET | `/install-jobs/{id}` | Fetch a single install job | OperationsCoordinator, SalesConsultant, Homeowner, PlatformAdmin |
| POST | `/projects/{id}/install-jobs/{jid}/depart` | Move a SCHEDULED job to EN_ROUTE | OperationsCoordinator |
| POST | `/projects/{id}/install-jobs/{jid}/complete` | Complete an EN_ROUTE job | OperationsCoordinator |
| POST | `/projects/{id}/install-jobs/{jid}/cancel` | Cancel a SCHEDULED job | OperationsCoordinator |
| POST | `/projects/{id}/permits` | File a permit | OperationsCoordinator |
| GET | `/projects/{id}/permits` | List permits on a project | OperationsCoordinator, SalesConsultant, Homeowner, PlatformAdmin |
| POST | `/projects/{id}/permits/{pid}/approve` | Approve (or re-approve) a permit | OperationsCoordinator |
| POST | `/projects/{id}/permits/{pid}/record-inspection` | Record inspection PASS/FAIL | OperationsCoordinator |
| POST | `/projects/{id}/service-tickets` | Open a callback/warranty ticket | Homeowner, ServiceTech, PlatformAdmin |
| GET | `/projects/{id}/service-tickets` | List service tickets on a project | Homeowner, ServiceTech, OperationsCoordinator, PlatformAdmin |
| GET | `/openings/{id}/service-tickets` | List service tickets for an opening | Homeowner, ServiceTech, OperationsCoordinator, PlatformAdmin |
| POST | `/projects/{id}/service-tickets/{sid}/dispatch` | Dispatch a tech | ServiceTech |
| POST | `/projects/{id}/service-tickets/{sid}/resolve` | Resolve a dispatched ticket | ServiceTech |
| POST | `/projects/{id}/service-tickets/{sid}/close` | Close a resolved ticket | ServiceTech |
| POST | `/projects/{id}/service-tickets/{sid}/reopen` | Reopen a resolved ticket | Homeowner |
| POST | `/referrals` | Create a referral | SalesConsultant, PlatformAdmin |
| GET | `/referrals` | List referrals filtered by `referrer_project_id` or `referred_project_id` | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/referrals/{id}` | Fetch a single referral | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/consultations/{id}` | Fetch a single consultation (flat) | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/consultations` | List consultations filtered by `project_id` | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/openings` | List openings filtered by `consultation_id` | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/quotes/{id}` | Fetch a single quote (flat; lazy expiry) | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/quotes` | List quotes filtered by `project_id` or `consultation_id` | SalesConsultant, OperationsCoordinator, Homeowner, PlatformAdmin |
| GET | `/financing-applications/{id}` | Fetch a single financing application (flat) | Homeowner, SalesConsultant, OperationsCoordinator, PlatformAdmin |
| GET | `/financing-applications` | List financing applications filtered by `quote_id` | Homeowner, SalesConsultant, OperationsCoordinator, PlatformAdmin |
| GET | `/manufacture-orders/{id}` | Fetch a single manufacture order (flat) | OperationsCoordinator, SalesConsultant, Homeowner, PlatformAdmin |
| GET | `/manufacture-orders` | List manufacture orders filtered by `project_id` or `quote_id` | OperationsCoordinator, SalesConsultant, Homeowner, PlatformAdmin |
| GET | `/permits/{id}` | Fetch a single permit (flat) | OperationsCoordinator, SalesConsultant, Homeowner, PlatformAdmin |
| GET | `/permits` | List permits filtered by `project_id` | OperationsCoordinator, SalesConsultant, Homeowner, PlatformAdmin |
| GET | `/service-tickets/{id}` | Fetch a single service ticket (flat) | Homeowner, ServiceTech, OperationsCoordinator, PlatformAdmin |
| GET | `/service-tickets` | List service tickets filtered by `project_id` or `opening_id` | Homeowner, ServiceTech, OperationsCoordinator, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_PROJECT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_QUOTE_VERSION` | 412 Precondition Failed |
| `ERR_CONSULTATION_NOT_MEASURED` | 409 Conflict |
| `ERR_NO_OPENINGS` | 422 Unprocessable Entity |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_PROJECT_ALREADY_CONTRACTED` | 409 Conflict |
| `ERR_PERMIT_NOT_APPROVED` | 409 Conflict |
| `ERR_GOODS_NOT_READY` | 409 Conflict |
| `ERR_CREW_JURISDICTION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_FINANCING_OVER_QUOTE` | 422 Unprocessable Entity |
| `ERR_REFERRER_NOT_COMPLETED` | 409 Conflict |
| `ERR_PROJECT_NOT_COMPLETED` | 409 Conflict |
| `ERR_VALIDATION_LIMIT` | 422 Unprocessable Entity |
