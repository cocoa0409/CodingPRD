# Gutter Leaf-Guard API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Gutter Leaf-Guard platform API, the back-office system that runs a whole-home gutter and leaf-guard sales, installation, and warranty business end to end. A homeowner enters as a **Lead**, is visited for an in-home linear-foot measure (**Appointment**), receives a per-foot **Quote** for a chosen gutter or guard product and color, may finance that quote, and — once the quote is accepted — becomes a scheduled install **Job** worked by a certified **Crew** under real weather constraints. After the install, the platform honors a lifetime clog-free warranty through adjudicated **WarrantyClaims**, and it pays existing customers for **Referrals** that convert.

The platform is, at its core, a pricing engine wrapped in a set of tightly coupled temporal workflows. Prices are tiered by the size of the run and adjusted for premium colors, drainage add-ons, and negotiated discounts; the same quote is priced twice — provisionally against the rep's rough estimate and finally against the surveyor's measured footage — and those two numbers must agree with the rules exactly. Money moves in one direction as a deal progresses (deposits, referral credits, financing schedules) and must be reversed cleanly when a job is cancelled or a lead is lost. Because several operators act on the same records — sales reps own the funnel, schedulers own the crews and the calendar, warranty agents own claims, and an administrator sits above all of them — the system enforces role boundaries, resource ownership, and optimistic concurrency so that no operator overwrites work they never saw.

All amounts of money in this system are integer counts of cents, every derived total is reproducible to the cent, and time is driven by a controllable logical clock rather than wall-clock time so that expiry and install-date gating are deterministic. The sections below define the global contract first, then the business workflows where the detailed rules live, and finally the endpoint and error reference tables.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply across every resource and endpoint. Most of it is a fixed contract; the business behavior it references is elaborated in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. If `X-User-Role` is absent or is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The four roles are `Admin`, `SalesRep`, `Scheduler`, and `WarrantyAgent`. When a syntactically valid, authenticated request asks for an operation the acting role is not permitted to perform, the response is `ERR_UNAUTHORIZED` (HTTP 403).

The four roles own disjoint surfaces, with the administrator overriding all of them:

- `Admin` is the platform operator. It manages the catalog (products, sales reps, and crews), drives the logical clock and the weather forecast, marks referrals paid, and may additionally perform any operation belonging to the three peer roles. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `SalesRep` owns the sales funnel: creating leads, booking and transitioning appointments, authoring, presenting, and transitioning quotes, offering financing, and recording referrals. When `X-User-Role` is `SalesRep`, `X-User-ID` is the `id` of the acting `SalesRep`. Ownership is enforced: a sales rep may act only on a `Lead` — and on the appointments and quotes belonging to that lead — whose `sales_rep_id` equals the acting `X-User-ID`. A sales rep attempting to act on another rep's lead (or on that lead's appointments or quotes) is rejected with `ERR_UNAUTHORIZED`.
- `Scheduler` owns install operations: scheduling jobs onto crews and dates, applying weather holds, and advancing jobs through the install lifecycle. When `X-User-Role` is `Scheduler`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `WarrantyAgent` owns warranty operations: filing and adjudicating lifetime clog-free warranty claims against completed jobs. When `X-User-Role` is `WarrantyAgent`, `X-User-ID` is likewise an opaque operator identifier, not tied to any persisted entity and not compared to any entity's `id`.

Every read (`GET`) endpoint is available to all four roles. Marking a referral paid is reserved to `Admin` alone, as are all catalog-creation, clock, and forecast operations.

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

List endpoints return their results in pages controlled by two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of leading items to skip; it defaults to 0 and may not be negative. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, every list is sorted by each resource's `created_at` timestamp in ascending order. Each list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the query before paging and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties

Every entity in this system — products, sales reps, crews, leads, appointments, quotes, financing plans, jobs, warranty claims, and referrals — carries the same four system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across all resources. Clients never supply it.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped once when the resource is created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at `1` on creation and increments by one on every mutation, used for optimistic concurrency control.

Whenever the server changes a resource — whether by a direct client action or by a cascade triggered elsewhere — it refreshes that resource's `updated_at` and increments its `version`. This applies equally to recomputed derived fields: when a crew's `booked_days`, a lead's `no_show_strikes`, or a lead's `credit_balance_cents` changes as a side effect of another operation, that owning resource is itself mutated, and its `updated_at` and `version` move accordingly.

### 2.5. Monetary Amounts, Precision, and Rounding

Every monetary field in this system is an integer number of cents; there are no fractional-cent values and no floating-point currency fields. Measured and estimated footage are decimal numbers of linear feet.

Wherever a calculation produces a monetary result, the rounding method is **round half up** to the nearest whole cent. Two ordering rules matter and are load-bearing:

- **Round per line, then sum.** When a total is assembled from several line items — for example a gutter charge, a premium-color surcharge, and a drainage add-on — each line item is rounded to whole cents *before* the lines are added together. The sum is not re-rounded.
- **Round per installment, then multiply.** When a financing schedule is derived, the per-installment payment is rounded to whole cents first, and the total cost of financing is that rounded payment multiplied by the number of installments — never the exact total computed once and rounded at the end. These two orders can differ by up to one cent per installment, and the per-installment order is the correct one.

Integer count fields such as install days and no-show strikes are exact integers; where a formula divides footage to obtain days, the result is rounded **up** to the next whole day.

### 2.6. Request Validation Order

For any operation, the server evaluates checks in a fixed priority order and returns the error of the first check that fails. A malformed request body — missing a required field, or carrying a value of the wrong type or an unrecognized enum member — is rejected up front with `ERR_VALIDATION` (HTTP 400). Beyond that structural check, the business validation ladder is:

1. **Authentication.** A missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** A role not permitted for the operation — including a sales rep acting on a lead they do not own — yields `ERR_UNAUTHORIZED` (403).
3. **Existence.** Every referenced resource must exist. The resource named in the URL path is checked first, then the foreign-key fields carried in the body, evaluated left to right in the order they are listed. The first missing reference produces the corresponding not-found error (for example `ERR_LEAD_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, and so on), each HTTP 404. For a request whose path identifies a resource and whose body also references others, the path resource's absence is reported before any body reference is examined.
4. **State.** The target resource must be in a valid originating state for the requested transition, including cross-entity state preconditions. Violations return HTTP 409 with the specific code for the situation: `ERR_INVALID_STATE` for a plain illegal transition, `ERR_APPOINTMENT_NOT_COMPLETED`, `ERR_QUOTE_NOT_ACCEPTED`, `ERR_QUOTE_EXPIRED`, or `ERR_JOB_NOT_COMPLETED` for the cross-entity cases.
5. **Weather safety** (scheduling and start only) — `ERR_WEATHER_UNSAFE` (422).
6. **Crew certification** (scheduling only) — `ERR_CREW_NOT_CERTIFIED` (422).
7. **Temporal overlap** — `ERR_REP_DOUBLE_BOOKED` or `ERR_CREW_DOUBLE_BOOKED` (409).
8. **Field-domain and catalog constraints** — such as non-positive footage, an out-of-range discount, an unavailable color, a self-referral, financing below the minimum, or invalid pagination (422).
9. **Fiscal ceiling** — financing above the maximum principal (`ERR_FINANCE_LIMIT_EXCEEDED`, 422).
10. **Optimistic concurrency** — a stale lead version on quote creation (`ERR_STALE_VERSION`, 412).

The safety, certification, and overlap steps (5 through 7) apply only where noted in Section 3; for a given endpoint, only the steps that are relevant to it are evaluated, but they are always evaluated in this relative order. In particular, for the scheduling of a job the weather check precedes the certification check, which precedes the crew-overlap check.

### 2.7. Optimistic Concurrency on Quote Creation

Creating a quote is the one operation guarded by optimistic concurrency, because a new quote supersedes the lead's prior open quote and advances the lead. A request to create a quote must include `expected_lead_version`, carrying the `version` of the target `Lead` that the client last observed. If `expected_lead_version` does not equal the lead's current `version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no quote is created. This prevents a client that read the lead before another writer advanced it from creating a quote against a stale view — for instance, from superseding a quote it never saw. This concurrency check is unique to quote creation; no other endpoint accepts or requires a version field in its body.

### 2.8. Cascading Consistency and Derived-Field Invariants

Many operations in this system mutate more than one resource. When a single action has secondary effects, all of them occur together, and each affected resource is mutated in full (its `updated_at` and `version` advance). The specific cascades — a lost lead declining its open quotes and cancelling its open appointments, an accepted quote spawning a job and winning a lead and paying a referrer, a cancelled job releasing crew days and clawing back referral credit — are described where they belong in Section 3, but the platform guarantees they are applied consistently and immediately.

Three derived fields are maintained as running aggregates and are recomputed whenever their inputs change:

- A crew's `booked_days` is the sum of `install_days` across all of that crew's jobs whose status is `SCHEDULED` or `IN_PROGRESS`. Jobs in `PENDING`, `WEATHER_HOLD`, `COMPLETED`, or `CANCELED` do not count. This aggregate is recomputed on every job schedule, weather hold, completion, and cancellation.
- A lead's `no_show_strikes` is the count of that lead's appointments in status `NO_SHOW`. It is recomputed each time one of the lead's appointments transitions to `NO_SHOW`.
- A lead's `credit_balance_cents`, as a referrer, is the sum of `payout_cents` across all referrals that name this lead as the referrer and whose status is `PAYABLE` or `PAID`. It is recomputed whenever such a referral becomes payable or is clawed back.

### 2.9. The Logical Clock and Weather Forecast

The platform runs on a controllable **logical clock** rather than wall-clock time. Before any clock has been set, the server's current time is `2026-05-01T00:00:00Z`. An administrator-only test-driving capability sets the current time by supplying a `to_iso8601` instant. The logical clock is what stamps a quote's `presented_at`, what determines whether a quote has expired, and what gates whether a job may begin installation on its assigned date.

Weather is likewise controllable. Each calendar date has a forecast condition, one of `CLEAR`, `RAIN`, or `SEVERE`; the default for every date, until set, is `CLEAR`. An administrator-only capability records the `condition` for a given date by supplying that `install_date` (a `YYYY-MM-DD` day) and the `condition`. Only a `SEVERE` forecast blocks operations — both scheduling a job onto a date and starting an in-progress install are refused when the relevant date is `SEVERE`. `CLEAR` and `RAIN` days impose no weather restriction.

## 3. Business Logic & Workflows

This section walks the business from catalog setup through the sales funnel, pricing, financing, installation, warranty, and referrals. The detailed field-level and rule-level behavior lives here, distributed across the workflow in which each rule takes effect.

### 3.1. Catalog and Workforce Setup

Before any selling happens, an administrator populates three catalog resources.

A **Product** is a sellable gutter or guard line. It carries a `name`, a `category` that is one of `GUTTER`, `LEAF_GUARD`, or `DOWNSPOUT`, and a `base_rate_cents_per_foot` giving the base install price per linear foot in whole cents. A product also defines its `available_colors` — the set of color values it may be quoted in, such as `WHITE`, `BRONZE`, `BLACK`, and `COPPER` — and a `premium_colors` subset of those that carry a surcharge (for example `COPPER`). The surcharge itself is `color_surcharge_cents_per_foot`, a per-foot amount in cents that defaults to 0 and is applied only when the chosen color is one of the premium colors. Finally, `is_active` marks whether the product is active and defaults to `true`; this flag is only recorded and is not enforced as a gate, so a quote may still be authored against an inactive product.

A **SalesRep** record carries the rep's `full_name`, a `region` service-area code (such as `NE` or `SE`), and an `is_active` flag defaulting to `true` marking whether the rep is active; this flag is only recorded and is not enforced as a gate, so appointments may still be booked for an inactive rep. A **Crew** carries a `name`, a `region`, and `is_certified_leaf_guard`, a flag defaulting to `false` that marks whether the crew may install leaf-guard-category jobs. A crew also exposes a computed `booked_days`, which is initialized to 0 at creation and thereafter reflects the crew's reserved install days as defined in Section 2.8.

Creating any of these three catalog resources is reserved to the administrator; all four roles may read them. Referencing a product, sales rep, or crew that does not exist yields `ERR_PRODUCT_NOT_FOUND`, `ERR_SALES_REP_NOT_FOUND`, or `ERR_CREW_NOT_FOUND` respectively.

### 3.2. The Sales Funnel: Leads and Their Progression

A **Lead** is a homeowner prospect. A sales rep (or the administrator) creates a lead with the homeowner's `full_name`, property `address`, `phone` callback number, `region`, and the owning `sales_rep_id`. A new lead begins with `status` of `NEW`, `no_show_strikes` of 0, and `credit_balance_cents` of 0. Leads may be listed with optional filters on `sales_rep_id` and `status`, and read individually.

A lead advances through `NEW`, `CONTACTED`, `APPOINTMENT_SET`, `QUOTED`, and terminates in either `WON` or `LOST`. Some of these moves are driven manually and some by the system. The manual lead action accepts a `to_status`: a rep may move a lead from `NEW` to `CONTACTED`, or move a lead to `LOST` from any non-terminal state (`NEW`, `CONTACTED`, `APPOINTMENT_SET`, or `QUOTED`). The system, in contrast, moves a lead from `NEW` or `CONTACTED` to `APPOINTMENT_SET` when the lead's first appointment is booked, from `APPOINTMENT_SET` to `QUOTED` when a quote is created for it, and from `QUOTED` to `WON` when one of its quotes is accepted.

Reaching `LOST` — whether by a rep's explicit request or automatically when the lead accumulates enough no-show strikes — fires a cleanup cascade on the lead's open work. Every quote for the lead that is in `DRAFT`, `PRESENTED`, or `REVISION_REQUESTED` is moved to `DECLINED`, and every appointment for the lead that is in `SCHEDULED` or `CONFIRMED` is moved to `CANCELED`, releasing those rep windows. `WON` and `LOST` are terminal; once a lead is in either state it accepts no further transitions.

### 3.3. In-Home Measure Appointments

An **Appointment** is a scheduled in-home measure visit. A sales rep books one by supplying the `lead_id` being measured, the `sales_rep_id` performing the measure, and the measure window as `scheduled_start` (inclusive) and `scheduled_end` (exclusive), both ISO 8601 UTC instants. A new appointment begins in `SCHEDULED`. Booking the lead's first appointment is what moves that lead from `NEW` or `CONTACTED` to `APPOINTMENT_SET`.

Booking is refused if it would collide with the rep's existing calendar. A rep's measure windows may not overlap: the window from `scheduled_start` to `scheduled_end`, extended by a fixed 30-minute travel buffer on each side so that consecutive visits leave time to drive between properties, must not overlap any window already booked for that same rep that is still in `SCHEDULED` or `CONFIRMED` status. A collision is rejected with `ERR_REP_DOUBLE_BOOKED`. Appointments may be listed with optional filters on `lead_id`, `sales_rep_id`, and `status`.

An appointment moves through its own lifecycle via a `to_status` action. From `SCHEDULED` it may be `CONFIRMED`, and from either `SCHEDULED` or `CONFIRMED` it may reach `COMPLETED`, be `CANCELED`, or be marked `NO_SHOW`. Completing an appointment requires the surveyor's `measured_linear_feet` — the actual measured gutter run — to be supplied and to be greater than 0; a missing or non-positive measurement is rejected with `ERR_INVALID_MEASUREMENT`, and on success the measurement is persisted on the appointment. Cancelling an appointment releases the rep window so it no longer counts toward overlap.

Marking an appointment `NO_SHOW` triggers a two-step cascade. First the lead's `no_show_strikes` is recomputed as the count of that lead's `NO_SHOW` appointments. Then, if that count reaches two or more, the lead is automatically moved to `LOST`, which in turn runs the lost-lead cleanup from Section 3.2 — declining the lead's open quotes and cancelling its remaining open appointments. `COMPLETED`, `CANCELED`, and `NO_SHOW` are terminal appointment states.

### 3.4. Building and Pricing a Quote

A **Quote** prices a specific product for a specific lead. A sales rep authors one by supplying the `lead_id`, the backing `appointment_id`, the authoring `sales_rep_id`, the `product_id`, the chosen `color`, and the rep's `estimated_linear_feet` — a rough footage used for the provisional price. Optional inputs are `downspout_count`, the number of drainage add-on units (default 0), and `discount_pct`, a requested discount as a fraction between 0 and 1 (default 0). The chosen color must be one of the product's `available_colors`, else `ERR_COLOR_UNAVAILABLE`; the requested discount must lie within the inclusive range 0 to 1, else `ERR_INVALID_DISCOUNT`; and the estimated footage must be greater than 0, else `ERR_INVALID_MEASUREMENT`. Because a quote creation also carries `expected_lead_version`, the optimistic-concurrency check of Section 2.7 applies as the final gate.

A new quote is born in `DRAFT`. Its `linear_feet` — the effective footage that drives the current total — is set equal to `estimated_linear_feet` while the quote is in `DRAFT` or `REVISION_REQUESTED`. Creating the quote advances the owning lead from `APPOINTMENT_SET` to `QUOTED`, supersedes any prior quote for that same lead that is still in `DRAFT`, `PRESENTED`, or `REVISION_REQUESTED` by moving it to `SUPERSEDED`, and increments the lead's `version` by one (which is exactly why a stale `expected_lead_version` is refused). Quotes may be listed with optional filters on `lead_id`, `appointment_id`, `sales_rep_id`, `product_id`, and `status`, and read individually; a reference to a quote that does not exist yields `ERR_QUOTE_NOT_FOUND`.

The price is assembled from the effective footage as follows, and this same procedure runs at creation (provisional), at presentation (final), and whenever a revision resets the quote to draft. First a **tier multiplier** is selected from the footage: it is 1.00 when the footage is below 200 linear feet, 0.95 when the footage is at least 200 but below 400 linear feet, and 0.90 when the footage is 400 linear feet or more. The **tier rate** is the product's `base_rate_cents_per_foot` multiplied by that tier multiplier, kept exact and not rounded. The **gutter line** is the footage multiplied by the tier rate, rounded half up to whole cents. The **color line** is the footage multiplied by the product's `color_surcharge_cents_per_foot`, rounded half up to whole cents, but only when the chosen color is one of the product's `premium_colors`; otherwise the color line is 0. The **downspout line** is `downspout_count` multiplied by a fixed 12,000 cents (that is, $120) per drainage unit. The `subtotal_cents` is the sum of those three rounded lines: gutter line plus color line plus downspout line.

The discount is resolved against the subtotal, not against the final total, to avoid a circular dependency. A **cap** is chosen from `subtotal_cents`: the cap is 0.10 when the subtotal is below 500,000 cents ($5,000), 0.15 when the subtotal is at least 500,000 but below 1,000,000 cents ($10,000), and 0.20 when the subtotal is 1,000,000 cents or more. The **effective discount fraction** is the smaller of the requested `discount_pct` and that cap. The `discount_cents` is the subtotal multiplied by the effective fraction, rounded half up to whole cents. Finally, `total_cents` is `subtotal_cents` minus `discount_cents`. These computed amounts — `subtotal_cents`, `discount_cents`, and `total_cents` — are stored on the quote.

### 3.5. Presenting, Revising, and Accepting Quotes

A draft quote is priced against an estimate; presenting it re-prices it against reality. The present action advances the quote from `DRAFT` to `PRESENTED`, and it is permitted only when the backing appointment (identified by the quote's `appointment_id`) has reached `COMPLETED`; otherwise it is rejected with `ERR_APPOINTMENT_NOT_COMPLETED`. On presentation, the appointment's `measured_linear_feet` is copied onto the quote's own `measured_linear_feet`, the quote's `linear_feet` is reset to that measured value, and the subtotal, discount, and total are recomputed from the measured footage using the exact same pricing and discount procedure of Section 3.4 — only now the effective footage is the measured footage rather than the estimate, so the final total may differ from the provisional one for the identical product, color, and downspout count. Presentation also stamps `presented_at` with the current logical-clock instant.

From `PRESENTED`, a rep may take the quote in one of three directions using the `to_status` action. It may be `DECLINED` outright. It may be sent back for revision as `REVISION_REQUESTED`, and from there returned to `DRAFT`; that reset restores `linear_feet` to `estimated_linear_feet`, recomputes the provisional total, and clears `presented_at`, so the quote can be re-presented later — the revision loop is `REVISION_REQUESTED` to `DRAFT` to `PRESENTED`. Or it may be `ACCEPTED`, which is the pivotal moment of the whole funnel. Acceptance is allowed only while the quote is still valid: the current logical-clock time must be no later than `presented_at` plus 30 days, the quote validity window; an attempt after that window is rejected with `ERR_QUOTE_EXPIRED`.

Accepting a quote fires a three-link cascade. First, a **Job** is created in `PENDING` for the accepted quote, computing its install days and deposit as described in Section 3.7. Second, the birth of that job moves the owning lead from `QUOTED` to `WON`. Third, the lead reaching `WON` moves any still-`PENDING` referral that names this lead as its referee to `PAYABLE`, computing that referral's payout and crediting the referrer as described in Section 3.9. A quote's terminal states are `ACCEPTED`, `DECLINED`, and `SUPERSEDED`.

### 3.6. Financing a Quote

A **FinancingPlan** offers the homeowner a payment schedule against a quote. A sales rep offers one by supplying the `quote_id`, a `plan_type` of either `DEFERRED_INTEREST` or `AMORTIZED`, an `apr_bps` annual percentage rate in basis points (for example 1200 for 12.00%, and 0 for a deferred-interest plan), a `term_months` count of monthly installments that must be at least 1 (a `term_months` below 1 is rejected with `ERR_VALIDATION`, HTTP 400), and an optional `promo_window_days` giving the same-as-cash promotional length in days from plan creation (default 0). The plan begins in `OFFERED`, and its `principal_cents` is a snapshot of the quote's `total_cents` taken at plan creation.

The financed principal must fall within the program's bounds: it must be at least 100,000 cents ($1,000), else `ERR_FINANCE_BELOW_MIN`, and it must not exceed 5,000,000 cents ($50,000), else `ERR_FINANCE_LIMIT_EXCEEDED`. From the principal the plan derives two figures, `monthly_payment_cents` and `total_cost_cents`, according to the plan type:

- For a `DEFERRED_INTEREST` plan, the `monthly_payment_cents` is the principal divided by `term_months`, rounded half up to whole cents, and the `total_cost_cents` equals the principal exactly — the plan is same-as-cash if the balance is cleared within the `promo_window_days`, so no interest is added.
- For an `AMORTIZED` plan, the monthly interest rate is the `apr_bps` divided by 10,000 and then by 12. The exact monthly payment is the standard amortization amount: the principal multiplied by that monthly rate, divided by the quantity one minus (one plus the monthly rate) raised to the power of negative `term_months`. The `monthly_payment_cents` is that exact monthly payment rounded half up to whole cents, and the `total_cost_cents` is that rounded monthly payment multiplied by `term_months`. For the same principal, an amortized plan's total cost exceeds the deferred-interest total by the financed interest.

A financing plan moves via a `to_status` action from `OFFERED` to `ACCEPTED` or `CANCELED`. Accepting a plan is permitted only when its backing quote (identified by the plan's `quote_id`) is itself in `ACCEPTED`; otherwise the acceptance is rejected with `ERR_QUOTE_NOT_ACCEPTED`. `ACCEPTED` and `CANCELED` are the plan's terminal states. Plans may be listed with optional filters on `quote_id` and `status`, and a missing plan reference yields `ERR_FINANCING_PLAN_NOT_FOUND`.

### 3.7. Scheduling and Installing Jobs

A **Job** is the install work that fulfills an accepted quote; jobs are never created directly, only born from the acceptance cascade of Section 3.5. At birth a job carries the `quote_id` it fulfills and the `lead_id` homeowner, starts in `PENDING`, and has a null `crew_id` and null `install_date` until it is scheduled. Two figures are computed at creation. The `install_days` — the crew-day span the job will occupy — is the accepted quote's `linear_feet` divided by 150 feet per crew day, rounded up to the next whole day. The `deposit_cents` collected at job creation is the quote's `total_cents` multiplied by 10 percent, rounded half up to whole cents. Jobs may be listed with optional filters on `quote_id`, `lead_id`, `crew_id`, and `status`, and a missing job reference yields `ERR_JOB_NOT_FOUND`.

Scheduling a job is a scheduler operation that assigns a `crew_id` and an `install_date` and moves the job from `PENDING` — or from `WEATHER_HOLD` — to `SCHEDULED`. Three checks run in this order. First, the forecast for the requested `install_date` must not be `SEVERE`, else `ERR_WEATHER_UNSAFE`. Second, if the job's product is of category `LEAF_GUARD`, the assigned crew's `is_certified_leaf_guard` must be true, else `ERR_CREW_NOT_CERTIFIED`. Third, the job's whole-day span — the inclusive range of days from the `install_date` through the `install_date` plus `install_days` minus one — must not overlap the day span of any other `SCHEDULED` or `IN_PROGRESS` job already assigned to that same crew, else `ERR_CREW_DOUBLE_BOOKED`. On success the crew and date are assigned and the crew's reserved `booked_days` grows by this job's `install_days`.

The remaining job transitions are driven by the scheduler through a `to_status` action:

- From `SCHEDULED`, the job may be placed on `WEATHER_HOLD`, which releases the crew reservation — the crew's `booked_days` shrinks by this job's `install_days`. Rescheduling a held job runs the same three scheduling checks and re-reserves the crew days, closing the `SCHEDULED` to `WEATHER_HOLD` to `SCHEDULED` recovery loop.
- From `SCHEDULED`, the job may move to `IN_PROGRESS`, but only on or after its assigned date — the current logical-clock date must be at least the `install_date`, else `ERR_INVALID_STATE` — and only when the current date's forecast is not `SEVERE`, else `ERR_WEATHER_UNSAFE`. Starting a job leaves the crew reservation in place.
- From `IN_PROGRESS`, the job may reach `COMPLETED`, which releases the crew reservation (the crew's `booked_days` shrinks by this job's `install_days`).
- A job may be `CANCELED` from `SCHEDULED`, `WEATHER_HOLD`, or `IN_PROGRESS`. Cancelling from `SCHEDULED` or `IN_PROGRESS` releases the crew reservation; cancelling from `WEATHER_HOLD` makes no crew-day change, because the hold already released it. In every cancellation, a referral clawback also runs: any referral that names this job's lead as its referee and is currently `PAYABLE` or `PAID` is moved to `CLAWED_BACK`, and the referrer's `credit_balance_cents` is decreased by that referral's `payout_cents`.

`COMPLETED` and `CANCELED` are the job's terminal states.

### 3.8. Lifetime Clog-Free Warranty Claims

A **WarrantyClaim** exercises the lifetime clog-free warranty on a completed install. A warranty agent files one by supplying the `job_id` and an `issue_type` of `CLOG`, `OVERFLOW`, or `DETACHMENT`. The claim may be filed only against a job that has reached `COMPLETED`; a claim against any other job state is rejected with `ERR_JOB_NOT_COMPLETED`. A new claim begins in `SUBMITTED`. Claims may be listed with an optional filter on `job_id` and on `status`, and a missing claim reference yields `ERR_WARRANTY_CLAIM_NOT_FOUND`.

A claim is adjudicated by the warranty agent through a `to_status` action. Moving from `SUBMITTED` to `UNDER_REVIEW` computes the claim's `estimated_remediation_cents`: a base amount chosen by issue type — 15,000 cents for a `CLOG`, 30,000 cents for an `OVERFLOW`, and 60,000 cents for a `DETACHMENT` — plus the linear footage of the claim's job (the `linear_feet` on the job's quote) multiplied by 200 cents per foot and rounded half up to whole cents. From `UNDER_REVIEW`, the agent may either move the claim to `APPROVED` or move it to `DENIED`; the denied branch is terminal and records no remediation cost, whereas the approved branch proceeds toward resolution. From `APPROVED`, moving to `RESOLVED` requires the supplied `actual_remediation_cents` to be present and at least 0, else `ERR_VALIDATION`; on success that actual cost is persisted on the claim and reconciled against the earlier estimate. `DENIED` and `RESOLVED` are the claim's terminal states.

### 3.9. Referrals and Referrer Credit

A **Referral** records that one existing customer sent the platform a new homeowner. A sales rep creates one with a `referrer_lead_id` (the existing customer who referred) and a `referee_lead_id` (the newly referred homeowner). The two must be different leads; a referral whose referrer and referee are the same is rejected with `ERR_SELF_REFERRAL`. A new referral begins in `PENDING` with `payout_cents` of 0. Referrals may be listed with optional filters on `referrer_lead_id`, `referee_lead_id`, and `status`, and a missing referral reference yields `ERR_REFERRAL_NOT_FOUND`.

A referral pays out when the referred homeowner converts. When the referee lead moves from `QUOTED` to `WON` on quote acceptance, any referral naming that lead as its referee that is still `PENDING` moves to `PAYABLE`. Its `payout_cents` is then computed as the smaller of two amounts: the referee's accepted quote `total_cents` multiplied by 3 percent and rounded half up to whole cents, or a hard cap of 50,000 cents ($500). Becoming payable increases the referrer lead's `credit_balance_cents` by that payout. The administrator alone may move a referral from `PAYABLE` to `PAID` using the `to_status` action; a paid referral still counts toward the referrer's `credit_balance_cents`.

The credit is reversed if the deal unwinds. When the referee's job is cancelled, any referral naming that lead as its referee that is `PAYABLE` or `PAID` is moved to `CLAWED_BACK`, and the referrer lead's `credit_balance_cents` is decreased by that referral's `payout_cents`. `CLAWED_BACK` is the referral's terminal state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state transition, the scheduling and presentation actions, and the clock and forecast controls — return `200 OK`. All list and read operations return `200 OK`. In the "Authorized Role(s)" column, "All roles" means `Admin`, `SalesRep`, `Scheduler`, and `WarrantyAgent`; where a peer role is named, `Admin` may also perform the operation as an override.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/products` | Create a product catalog entry | Admin |
| GET | `/api/products/{id}` | Get a product | All roles |
| POST | `/api/sales-reps` | Create a sales rep | Admin |
| GET | `/api/sales-reps/{id}` | Get a sales rep | All roles |
| POST | `/api/crews` | Create an install crew | Admin |
| GET | `/api/crews/{id}` | Get a crew (includes computed booked days) | All roles |
| POST | `/api/leads` | Create a lead | SalesRep, Admin |
| GET | `/api/leads/{id}` | Get a lead | All roles |
| GET | `/api/leads` | List leads (filter by rep or status) | All roles |
| POST | `/api/leads/{id}/transition` | Transition a lead (CONTACTED, LOST) | SalesRep, Admin |
| POST | `/api/appointments` | Book an in-home measure appointment | SalesRep, Admin |
| GET | `/api/appointments/{id}` | Get an appointment | All roles |
| GET | `/api/appointments` | List appointments (filter by lead or rep) | All roles |
| POST | `/api/appointments/{id}/transition` | Transition an appointment (CONFIRMED, COMPLETED, CANCELED, NO_SHOW) | SalesRep, Admin |
| POST | `/api/quotes` | Create a quote for a lead | SalesRep, Admin |
| GET | `/api/quotes/{id}` | Get a quote | All roles |
| GET | `/api/quotes` | List quotes (filter by lead, appointment, rep, product, status) | All roles |
| POST | `/api/quotes/{id}/present` | Present a draft quote (final re-pricing from measured feet) | SalesRep, Admin |
| POST | `/api/quotes/{id}/transition` | Transition a quote (ACCEPTED, DECLINED, REVISION_REQUESTED, DRAFT) | SalesRep, Admin |
| POST | `/api/financing-plans` | Offer a financing plan for a quote | SalesRep, Admin |
| GET | `/api/financing-plans/{id}` | Get a financing plan | All roles |
| GET | `/api/financing-plans` | List financing plans (filter by quote) | All roles |
| POST | `/api/financing-plans/{id}/transition` | Transition a financing plan (ACCEPTED, CANCELED) | SalesRep, Admin |
| GET | `/api/jobs/{id}` | Get a job | All roles |
| GET | `/api/jobs` | List jobs (filter by quote, lead, crew, status) | All roles |
| POST | `/api/jobs/{id}/schedule` | Assign crew and install date to a pending or held job | Scheduler, Admin |
| POST | `/api/jobs/{id}/transition` | Transition a job (WEATHER_HOLD, IN_PROGRESS, COMPLETED, CANCELED) | Scheduler, Admin |
| POST | `/api/warranty-claims` | File a warranty claim against a completed job | WarrantyAgent, Admin |
| GET | `/api/warranty-claims/{id}` | Get a warranty claim | All roles |
| GET | `/api/warranty-claims` | List warranty claims (filter by job) | All roles |
| POST | `/api/warranty-claims/{id}/transition` | Transition a warranty claim (UNDER_REVIEW, APPROVED, DENIED, RESOLVED) | WarrantyAgent, Admin |
| POST | `/api/referrals` | Record a referral linking a referrer to a referee lead | SalesRep, Admin |
| GET | `/api/referrals/{id}` | Get a referral | All roles |
| GET | `/api/referrals` | List referrals (filter by referrer or referee lead) | All roles |
| POST | `/api/referrals/{id}/transition` | Mark a payable referral paid | Admin |
| POST | `/_clock/set_current_utc` | Set the logical clock | Admin |
| POST | `/_weather/set_forecast` | Set the forecast condition for a date | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_SALES_REP_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_LEAD_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_FINANCING_PLAN_NOT_FOUND` | 404 |
| `ERR_JOB_NOT_FOUND` | 404 |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_APPOINTMENT_NOT_COMPLETED` | 409 |
| `ERR_QUOTE_NOT_ACCEPTED` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_JOB_NOT_COMPLETED` | 409 |
| `ERR_REP_DOUBLE_BOOKED` | 409 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_WEATHER_UNSAFE` | 422 |
| `ERR_CREW_NOT_CERTIFIED` | 422 |
| `ERR_INVALID_MEASUREMENT` | 422 |
| `ERR_INVALID_DISCOUNT` | 422 |
| `ERR_COLOR_UNAVAILABLE` | 422 |
| `ERR_SELF_REFERRAL` | 422 |
| `ERR_FINANCE_BELOW_MIN` | 422 |
| `ERR_FINANCE_LIMIT_EXCEEDED` | 422 |
