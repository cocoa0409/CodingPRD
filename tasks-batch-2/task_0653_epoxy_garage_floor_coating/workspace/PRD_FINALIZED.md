# Epoxy Garage-Floor Coating API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Epoxy Garage-Floor Coating API, the back-office system that carries a residential garage-floor coating job from first phone call all the way through to a cured floor under warranty. The business runs on a deceptively simple promise — measure a garage, grind and patch the slab, lay down a flake or metallic coating in a single day, and stand behind the result — but the economics underneath that promise are intricate. Every floor is a different size and in a different condition, prep scope drives most of the labor cost, the coating chemistry dictates how long the slab must cure before a car can roll back in, and the price quoted off a clipboard at the kitchen table is never quite the price that the crew measures with the slab swept clean. The API exists to keep all of that honest.

Two ideas organize the whole system. The first is that pricing happens twice: an **estimate** is priced from the measurements a sales technician takes during the in-home assessment, and a **final** quote is re-priced from the square footage the install crew verifies on the day of the job. The second is that a project advances along two independent tracks at once — a **sales** track (lead, assessed, quoted, accepted, declined) and a **build** track (pre-build, scheduled, installed, curing, complete, cancelled) — so that a job can be sold and a job can be built without the two pipelines tripping over each other. Layered on top are seasonal and volume pricing rules, a one-day crew-capacity and cure-window scheduling model running on a logical clock, a hot-tire and peel warranty whose payout decays over a fifteen-year term, and a referral program that issues account credit when a referred job completes and quietly claws it back if that job is later cancelled. The sections that follow define the contract precisely where the API surface must be unambiguous, and describe the business behavior in prose everywhere a human operator needs to understand *why* a rule exists.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that govern every endpoint. Resource collections are mounted at the flat top level — there is no shared URL prefix — so projects live under `/projects`, customers under `/customers`, crews under `/crews`, and so on.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly six roles, spelled precisely as follows: `PlatformAdmin`, `SalesRep`, `Scheduler`, `Crew`, `WarrantyAgent`, and `Customer`.

- A `PlatformAdmin` is an operations administrator who manages the catalogs, drives the logical clock, and cancels projects. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `SalesRep` owns the sales pipeline — leads, assessments, quotes, and referrals. When `X-User-Role` is `SalesRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- A `Scheduler` owns install booking and the curing milestone. When `X-User-Role` is `Scheduler`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- A `WarrantyAgent` owns warranties and the claim/callback lifecycle. When `X-User-Role` is `WarrantyAgent`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity.
- A `Crew` is the on-site install crew that starts and completes installs. When `X-User-Role` is `Crew`, `X-User-ID` is the `id` of the acting `Crew` entity; ownership checks on any resource that references a `Crew` compare the resource's crew foreign key to `X-User-ID`.
- A `Customer` is the homeowner. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's customer foreign key to `X-User-ID`. Specifically, when a `Customer` accepts or declines a quote, files a warranty claim, or resubmits a claim, the system requires `X-User-ID` to equal the `customer_id` of the owning project; otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

Each list response carries the pagination bookkeeping in the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in this system carries a server-minted `id` that is a UUID with no type prefix — it is an identity handle only and conveys no other meaning. Every resource also carries a `created_at` timestamp, formatted as an ISO 8601 UTC instant with three fractional digits, recording when the row was first created.

All entities in this system additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed to the current instant on every mutation. The `version` begins at 1 when a resource is created and increments by exactly 1 on every subsequent mutation — including mutations that happen as a side effect of another operation (a cascade). Because the `Project` is the hub through which most cascades flow, its `version` advances frequently: it is bumped on assessment recording, on every quote send, on quote acceptance, on decline, on install booking, on install completion, on the curing milestone, and on cancellation. Wherever a workflow below says a step "advances the project," understand that the project's `version` is incremented and its `updated_at` refreshed as part of that step.

### 2.5. Logical Clock and Scheduled Milestones

Time in this system is not wall-clock time. The server maintains a single **logical clock** that governs install dates, cure deadlines, and warranty coverage windows. On startup the clock reads exactly `2026-04-01T00:00:00Z`, and before any client sets it the clock holds at that default and never falls back to the host's real time. A `PlatformAdmin` may advance the clock by supplying a target instant in the `to_iso8601` field of the clock-setting capability. Every temporal comparison in the business rules below — whether an install may start, whether a floor may be marked cured, whether a warranty claim is still in its coverage window — is evaluated against the logical clock's current reading, never against the operating system clock.

### 2.6. Nested Resource Retrieval and Reference Resolution

Many paths address a child resource through its parent — for example, the assessments, quotes, install jobs, and warranties that hang beneath a project, or the claims that hang beneath a warranty. When a path contains more than one resource identifier, the system validates them strictly left to right and rejects the request with `ERR_NOT_FOUND` at the *first* identifier that does not resolve to an existing resource, before considering any later identifier or any business rule.

A second, distinct check governs reference fields carried in a request body rather than in the path. On create operations whose body names another row — `customer_id`, `crew_id`, `coating_system_id`, `color_option_id`, `financing_plan_id`, `assessment_id`, or `project_id` — each such reference must resolve to an existing row; if any does not, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Path-identifier resolution (`ERR_NOT_FOUND`) is a separate concern from body-reference resolution (`ERR_REFERENCE_NOT_FOUND`); the former is a 404 on the URL, the latter a 404 on a payload pointer.

### 2.7. Monetary Precision and Rounding

All money in this system is expressed in whole integer **cents** and is never represented as a fractional or floating value in storage or response. Wherever a calculation produces a non-integer cent amount, the result is rounded **half up** to the nearest whole cent. The pricing engine applies this rounding at each pinned intermediate step rather than only at the end: the system material subtotal is rounded after any complexity multiplier, the prep-labor subtotal is rounded after the seasonal multiplier, and the volume discount is rounded when computed. Constants that are themselves exact whole-cent amounts — the trip fee, for instance — are added without rounding. Referral credit is an exact integer-cent quantity that is never rounded. The financing monthly-rate intermediate is computed at full floating precision and only the final monthly payment is rounded half up to whole cents.

### 2.8. Validation Ordering

When several validations could apply to a single request, they are evaluated in a fixed priority order, and the first one that fails determines the error returned. The ordering, highest priority first, is: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the operation (`ERR_FORBIDDEN_ROLE`); (3) resource-ownership for `Customer`-driven actions, namely accepting a quote, declining a project, filing a claim, and resubmitting a claim (`ERR_NOT_RESOURCE_OWNER`); (4) existence of every path-referenced resource, left to right (`ERR_NOT_FOUND`); (5) existence of every body reference field (`ERR_REFERENCE_NOT_FOUND`); (6) the color-belongs-to-system check on quote creation (`ERR_COLOR_SYSTEM_MISMATCH`); (7) the self-referral check on referral creation (`ERR_SELF_REFERRAL`); (8) the state-machine guard that the target is in a state from which the transition is defined (`ERR_INVALID_STATE`); (9) the cross-dimension guard that a project's sales track has reached acceptance before its build track may schedule (`ERR_SALES_NOT_ACCEPTED`); (10) the assessment-must-be-approved check on quote creation (`ERR_ASSESSMENT_NOT_APPROVED`); (11) the metallic-certified crew check (`ERR_CREW_NOT_METALLIC_CERTIFIED`); (12) the crew same-day double-booking check (`ERR_CREW_DAY_DOUBLE_BOOKED`); (13) the site cure-window overlap check (`ERR_SITE_CURE_WINDOW_OVERLAP`); (14) the crew daily-capacity check (`ERR_CREW_CAPACITY_EXCEEDED`); (15) the cure-window-elapsed gate on marking cured (`ERR_CURE_WINDOW_NOT_ELAPSED`); (16) the install-date-reached gate on starting (`ERR_INSTALL_DATE_NOT_REACHED`); (17) the coverage-window gate on claim filing (`ERR_COVERAGE_EXPIRED`); (18) the covered-defect check on claim approval (`ERR_DEFECT_NOT_COVERED`); (19) the financing-eligibility check (`ERR_FINANCING_PRINCIPAL_TOO_LOW`); (20) the optimistic-concurrency stale-version check (`ERR_STALE_PROJECT_VERSION`); and (21) the catch-all field-presence and constraint check (`ERR_VALIDATION`). Where two checks both guard the same endpoint, the lower number wins — for instance, on install booking the cross-dimension acceptance guard is evaluated before the metallic-crew check, which is evaluated before the same-day collision check, which is evaluated before the cure-window overlap check, which is evaluated before the capacity check.

### 2.9. Optimistic Concurrency Control

Two project-level write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a project. In both cases the request body must carry an `expected_project_version` field — it is not optional — holding the `version` of the `Project` that the client last observed. The server compares that value against the project's current `version`; if they differ, the project has been advanced by some other writer since the client read it, and the request is rejected with `ERR_STALE_PROJECT_VERSION` at HTTP 412.

The first guarded operation is quote acceptance. When a homeowner accepts a sent quote, `expected_project_version` must equal the project's current `version`; if a newer quote was sent on the same project after the client's last read (which would supersede prior quotes upon acceptance), the project's `version` has moved on, the client's notion of which quote is current is stale, and the acceptance is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). The second guarded operation is project cancellation. When an administrator cancels a project, `expected_project_version` must equal the project's current `version`; if a scheduling action or an install completion advanced the project between the administrator's last read and the cancel, the cancel is acting on a stale view and is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). No other endpoint takes a version field, and operations not named here perform no concurrency check.

### 2.10. Parallel Status Dimensions and Cascading Consistency

A `Project` is unusual in that it carries two enumerated status fields that advance independently. The `sales_status` dimension tracks the commercial pipeline through the values `LEAD`, `ASSESSED`, `QUOTED`, `ACCEPTED`, and `DECLINED`. The `build_status` dimension tracks fulfilment through the values `PRE_BUILD`, `SCHEDULED`, `INSTALLED`, `CURING`, `COMPLETE`, and `CANCELLED`. The build track does not begin advancing until the sales track has reached `ACCEPTED`; before that point, any attempt to schedule is refused. The two dimensions are stored on the same record but the state machines that move them are separate, so a single operation may advance one, the other, or — on completion — chain several build transitions within one call.

Consistency across related rows is maintained immediately. Whenever a transition declares a side effect on another row — superseding an assessment, superseding sibling quotes, voiding a warranty, closing claims, cancelling install jobs, converting or clawing back a referral, adjusting a customer's credit — that side effect is applied within the same operation, and any row it mutates has its own `updated_at` refreshed and, where the row carries a `version`, its `version` incremented. The detailed cascades are described in the workflow narratives of section 3.

## 3. Business Logic & Workflows

### 3.1. Catalog Setup: Coating Systems, Colors, Crews, and Financing

Before any selling happens, a `PlatformAdmin` populates the catalogs that quotes and installs draw on. A **coating system** is created with a display `name`, a `family`, and a `sku`, and may carry an `active` flag indicating whether it is selectable on new quotes (defaulting to true when omitted). The `family` is one of `FLAKE` or `METALLIC`, and the `sku` is one of `FLAKE_STANDARD`, `FLAKE_PREMIUM`, or `METALLIC`; the family drives both cure timing and material complexity while the sku selects the per-square-foot material rate. The system also derives a read-only `requires_metallic_certified_crew` flag, which is true exactly when the family is `METALLIC` and false otherwise; this flag is what later forces a metallic job onto a certified crew.

A **color option** belongs to a coating system. It is created with the owning `coating_system_id`, a blend `name`, a manufacturer `flake_blend_code`, and an optional `active` flag defaulting to true. Because a color blend is meaningful only in the context of its system, the system this color belongs to is recorded so that a later quote can be checked for consistency between its chosen color and its chosen system.

A **financing plan** is created with a `name`, an interest rate `apr_bps` expressed in basis points (so 999 means 9.99 percent), a `term_months` count of monthly payments, an optional `min_principal_cents` minimum financed amount that defaults to 0 when omitted, and an optional `active` flag defaulting to true. The rate in basis points must be at least 0 and at most 3500; the term must be at least 1 month and at most 84 months; the minimum principal must be at least 0.

A **crew** is created with a `name`, an optional `metallic_certified` flag (defaulting to false) recording whether the crew may install metallic systems, a `max_sqft_per_day` capacity ceiling that must be at least 1, and an optional `active` flag defaulting to true. The capacity ceiling is the largest single-day floor area the crew can lay, and it is checked against a job's priced area before a booking is allowed.

### 3.2. Customers and the Referral Program

A `PlatformAdmin` or a `SalesRep` registers a **customer** by supplying a `full_name` and an `email`; the email is unique among customers. On creation the server mints a `referral_code` — a short code that other customers can cite to credit this customer — and initializes `account_credit_balance_cents` to 0. That credit balance is not directly editable; it is a conserved quantity that moves only through the referral lifecycle described below. At any time the balance equals the referral credit amount of fifteen thousand cents multiplied by the number of referrals naming this customer as referrer that currently sit in the converted state — converting a referral adds one such credit, and clawing one back removes it, so across all customers the total outstanding credit always equals fifteen thousand cents times the count of all converted referrals.

A `SalesRep` creates a **referral** by supplying a `referrer_customer_id` (the customer who owns the cited code), a `referred_customer_id` (the new customer), and a `project_id` pointing at the referred customer's project that may convert. The referred customer must differ from the referrer; a request where the two are the same is rejected with `ERR_SELF_REFERRAL`. A new referral is born in `PENDING` status with its `credit_cents` set to fifteen thousand, and it pins itself to the referred project by setting that project's `referral_id`. A referral may also come into being implicitly: when a project is created with a referral code that matches some other customer's `referral_code`, the system creates the `PENDING` referral row and sets the new project's `referral_id` automatically. A referral converts when the referred project's build track reaches completion, expires if the referred project's sales track is declined while still pending, and is clawed back if a converted project is later cancelled — these transitions and their credit effects are detailed in sections 3.7 and 3.8.

### 3.3. Originating a Project and Recording the Assessment

A `SalesRep` opens a **project** for a homeowner by supplying the `customer_id` it is for, the five-digit `site_zip` of the install address, and optionally a `referral_code` to credit. A new project starts with `sales_status` of `LEAD`, `build_status` of `PRE_BUILD`, and `version` of 1; its `accepted_quote_id` and `referral_id` begin null, the latter being populated only if the supplied referral code matched another customer's code as described above.

The first substantive step is the **assessment**, recorded by a `SalesRep` against a project whose sales track is still at `LEAD` or `ASSESSED` (re-measuring is allowed right up until a quote has been sent, but not after). The technician submits the measured area `measured_sqft` (at least 1), the `oil_stain_pct` of the floor showing oil staining (0 through 100), the `crack_density` in cracks per hundred square feet, the total `crack_linear_ft` of measured cracking (at least 0), a `spalling` boolean for surface spalling, and the slab `moisture_pct` reading (0 through 100). Recording an assessment advances the project's sales track to `ASSESSED` (a `LEAD → ASSESSED` move, or an `ASSESSED → ASSESSED` re-measure), creates the assessment in `APPROVED` status, and bumps the project `version`.

A project keeps at most one `APPROVED` assessment at a time. When a newer assessment is recorded, any prior `APPROVED` assessment on the same project is transitioned to `SUPERSEDED`, and the new one becomes the project's single approved measurement. The assessment's `project_id` records which project was measured.

From the six raw inputs the system computes a weighted **condition score**, stored in `condition_score` as a whole number from 0 to 100. The crack density is first normalized: it is capped at 50 and the capped value is divided by 50 and multiplied by 100 to give a 0-to-100 crack figure. Spalling contributes 100 points when present and 0 when absent. The raw score is then the sum of four weighted terms — 30 percent of the oil-stain percentage, 40 percent of the normalized crack figure, 20 percent of the spalling points, and 10 percent of the moisture percentage — and the raw score is rounded half up to the stored integer `condition_score`. From that score the system derives the `prep_tier`, the grind-and-crack prep scope, which is `HEAVY` when the score is at least 70, otherwise `MODERATE` when the score is at least 35, and otherwise `LIGHT`. Both threshold comparisons are inclusive of their lower bound.

The assessment also records `billable_crack_ft`, the crack footage that will be billed beyond the allowance baked into the chosen prep tier. The allowance is 0 linear feet for `LIGHT`, 10 linear feet for `MODERATE`, and 25 linear feet for `HEAVY`. The billable figure is the measured `crack_linear_ft` minus the tier's included allowance, floored at 0 so it can never go negative.

### 3.4. Pricing a Quote: The Estimate

With an approved assessment in hand, a `SalesRep` builds an **estimate quote** by selecting the system and colorway and the timing. The create call carries the `assessment_id` of the approved assessment whose prep tier, square footage, and cracking feed pricing, the `coating_system_id` of the chosen system, the `color_option_id` of the chosen color, an `install_season` bucket, and an optional `financing_plan_id` (its absence means pay-in-full). The referenced assessment must be the project's `APPROVED` assessment and not a `SUPERSEDED` one; otherwise the quote is rejected with `ERR_ASSESSMENT_NOT_APPROVED`. The chosen color must belong to the chosen system — that is, the color option's `coating_system_id` must equal the quote's `coating_system_id` — or the request is rejected with `ERR_COLOR_SYSTEM_MISMATCH`. The `install_season` is one of `PEAK`, `STANDARD`, or `OFF`, and it drives the seasonal labor multiplier. A new estimate is created with `variant` of `ESTIMATE` and `status` of `DRAFT`, and its `project_id` ties it to the project.

The pricing engine runs in a pinned order and stores each component on the quote. First it determines the billable area `priced_sqft`, which for an estimate is the greater of the assessment's `measured_sqft` and the small-job floor of 250 square feet. The **system material** subtotal `system_material_cents` is the per-square-foot material rate for the chosen sku — 350 cents for `FLAKE_STANDARD`, 500 cents for `FLAKE_PREMIUM`, and 800 cents for `METALLIC` — multiplied by the priced area; if the system's family is `METALLIC`, that material subtotal is then multiplied by the metallic complexity factor of 1.20 and rounded half up to whole cents (the complexity factor applies to material only, never to labor).

Next the **prep labor** subtotal `prep_labor_cents` is built. The base labor is the per-square-foot prep rate for the assessment's tier — 150 cents for `LIGHT`, 275 cents for `MODERATE`, and 450 cents for `HEAVY` — multiplied by the priced area. To that is added a crack adder: the crack feet beyond the tier's included allowance (the measured crack length minus the included feet, floored at 0) multiplied by 900 cents per foot. The base labor plus the crack adder is then multiplied by the seasonal multiplier for the chosen season — 1.15 for `PEAK`, 1.00 for `STANDARD`, and 0.90 for `OFF` — and rounded half up to whole cents to give `prep_labor_cents`.

The order of the remaining steps is fixed and consequential. The pre-discount base is the sum of `system_material_cents` and `prep_labor_cents`. A **volume discount** is keyed on that pre-discount base: the discount percentage is 10 percent when the base is at least 600,000 cents, otherwise 5 percent when the base is at least 300,000 cents, and otherwise 0 percent; both thresholds are inclusive. The system stores that tier in `volume_discount_pct_bps` as basis points — 0, 500, or 1000 — and computes `discount_cents` as the pre-discount base multiplied by the discount percentage, rounded half up. The flat trip fee `mobilization_cents` is exactly 25,000 cents. The `grand_total_cents` is the pre-discount base minus the discount, plus the mobilization fee — the mobilization fee is added *after* the discount and is never itself discounted.

If the quote names a financing plan, the monthly payment is amortized and stored in `monthly_payment_cents`; otherwise that field is 0. The financing math treats the quote's `grand_total_cents` at creation as the principal. The monthly rate is the plan's `apr_bps` divided by ten thousand and then by twelve. When that monthly rate is exactly zero, the monthly payment is the principal divided by the `term_months`, rounded half up. Otherwise the monthly payment is the principal times the monthly rate times one-plus-the-rate raised to the term, all divided by one-plus-the-rate raised to the term minus one, with the final figure rounded half up to whole cents. A financing plan may be selected only if the quote's `grand_total_cents` is at least the plan's `min_principal_cents`; a principal below that floor is rejected with `ERR_FINANCING_PRINCIPAL_TOO_LOW`.

### 3.5. Sending, Accepting, and Declining

A `SalesRep` **sends** a draft quote to the homeowner, moving the quote's `status` from `DRAFT` to `SENT`. Sending is meaningful at the project level: the very first send on a project advances the sales track from `ASSESSED` to `QUOTED`, and a first send requires that the sales track be at `ASSESSED` and that an approved assessment exists. Every send — the first one and every later one — increments the project `version`, because each send changes the set of offers currently on the table.

A `Customer` **accepts** a sent quote, which is the pivot from selling to building. Acceptance requires that the project's sales track be at `QUOTED`, that the quote's `status` be `SENT`, that the quote belong to this project, and that the supplied `expected_project_version` match the project's current `version` (the optimistic-concurrency guard of section 2.9). On success the quote's `status` becomes `ACCEPTED`, the sales track moves `QUOTED → ACCEPTED`, the project's `accepted_quote_id` is set to point at the accepted quote, and every other quote on the project still in `SENT` or `DRAFT` is moved to `SUPERSEDED`. If the project carries a referral that is still `PENDING`, it remains `PENDING` at this point — a referral converts only when the install completes, not when the quote is accepted. The project `version` is incremented.

A `Customer` may **decline** the project outright, moving the sales track to `DECLINED`. A decline is permitted only while the sales track is at `LEAD`, `ASSESSED`, or `QUOTED` and the build track is still at `PRE_BUILD`; once a project has been scheduled, it can no longer be declined, and a late decline is rejected with `ERR_DECLINE_AFTER_SCHEDULED`. The two guards are evaluated in a fixed order: the build-track check comes first, so whenever the build track has left `PRE_BUILD` — that is, it is at `SCHEDULED`, `INSTALLED`, `CURING`, `COMPLETE`, or `CANCELLED`, regardless of the sales state — the decline is rejected with `ERR_DECLINE_AFTER_SCHEDULED`. Only when the build track is still at `PRE_BUILD` is the sales-state guard then applied, and a project still at `PRE_BUILD` whose sales track is not one of `LEAD`, `ASSESSED`, or `QUOTED` (for example an already-`DECLINED` project) is rejected with `ERR_INVALID_STATE`. Declining supersedes every non-terminal quote on the project (moving each to `SUPERSEDED`), and if the project's referral is still `PENDING` it transitions to `EXPIRED`. The project `version` is incremented. The `DECLINED` sales state is terminal.

### 3.6. Booking and Running the One-Day Install

Once a project's sales track has reached `ACCEPTED`, a `Scheduler` **books the install** by supplying the `crew_id` of the chosen crew and the `install_date`, the UTC start instant of the one-day job. This is the move that advances the build track from `PRE_BUILD` to `SCHEDULED`, and it is guarded by a sequence of checks evaluated in the priority order of section 2.8. The project's sales track must already be at `ACCEPTED`, or the booking is refused with `ERR_SALES_NOT_ACCEPTED`. The build track must be at `PRE_BUILD`. If the accepted quote's coating system is in the `METALLIC` family, the chosen crew must be `metallic_certified`; a metallic job sent to an uncertified crew is rejected with `ERR_CREW_NOT_METALLIC_CERTIFIED`.

Two scheduling-collision checks then apply, and they are deliberately different in shape. The first is a **crew same-day** check: the chosen crew may not already hold another install job in `BOOKED` or `IN_PROGRESS` status whose `install_date` falls on the same UTC calendar day — collision is decided purely by whether the two dates land in the same day bucket, and a clash is rejected with `ERR_CREW_DAY_DOUBLE_BOOKED`. The second is a **site cure-window** check on the customer: the new job's cure window — the half-open interval running from its `install_date` up to but not including its `vehicle_traffic_ok_at` — may not overlap the cure window of any other non-terminal install job (one in `BOOKED`, `IN_PROGRESS`, or `COMPLETED`) belonging to a *different* project of the *same* customer. Two windows that merely touch at an endpoint, where one window's `vehicle_traffic_ok_at` equals the other's `install_date`, do not overlap. A genuine overlap is rejected with `ERR_SITE_CURE_WINDOW_OVERLAP`. Finally, the accepted quote's `priced_sqft` must not exceed the crew's `max_sqft_per_day`, or the booking is rejected with `ERR_CREW_CAPACITY_EXCEEDED`.

A successful booking creates an **install job** in `BOOKED` status, ties it to the project via `project_id`, and computes the cure schedule. The `install_end` is the `install_date` plus the eight-hour install duration. The `foot_traffic_ok_at`, when the floor may bear foot traffic, is the install end plus 24 hours. The `vehicle_traffic_ok_at`, the hot-tire cure deadline after which a vehicle may return, is the install end plus 72 hours, with an additional 24 hours added when the accepted quote's coating system is in the `METALLIC` family (so a metallic floor cures 96 hours past install end rather than 72). All of these are exact UTC datetime computations at second-level precision. Booking also increments the project `version`.

On the day of the job, a `Crew` **starts** the install, moving the install job's `status` from `BOOKED` to `IN_PROGRESS`. A start is allowed only when the logical clock has reached or passed the job's `install_date`; an attempt before that instant is rejected with `ERR_INSTALL_DATE_NOT_REACHED`.

When the floor is laid, the `Crew` **completes** the install, supplying the crew-verified on-site numbers `as_measured_sqft` (at least 1) and `as_measured_crack_ft` (at least 0). Completion requires the install job to be `IN_PROGRESS` and the measured area to be present and at least 1. This single call does a great deal of work. The install job's `status` becomes `COMPLETED`, capturing the as-measured numbers. The system then re-prices the job as a **final quote**: a new quote with `variant` of `FINAL` is created using exactly the same pricing engine as the estimate, except that its billable area comes from the install job's `as_measured_sqft` and its crack figure from `as_measured_crack_ft` rather than from the assessment — so a slab that measured differently in the field produces a different `grand_total_cents`. The previously accepted estimate quote is moved to `SUPERSEDED`, and the project's `accepted_quote_id` is repointed to the new final quote. On the build track, completion drives `SCHEDULED → INSTALLED → CURING` within the one call — `INSTALLED` is a transient label the build status passes through, and the build track comes to rest at `CURING`. The project `version` is incremented.

After the cure deadline has passed, a `Scheduler` **marks the floor cured**, moving the install job's `status` from `COMPLETED` to `CURED` and the build track from `CURING` to `COMPLETE`. This is permitted only when the logical clock has reached or passed the job's `vehicle_traffic_ok_at`; an early attempt is rejected with `ERR_CURE_WINDOW_NOT_ELAPSED`. Marking cured creates the warranty (section 3.7), increments the project `version`, and — if the project carries a referral still in `PENDING` — converts it (section 3.8).

### 3.7. Warranty Coverage and the Callback Claim Loop

When an install is marked cured, the system creates a **warranty** in `ACTIVE` status, tied to the project via `project_id` and pointing at the originating install job via `install_job_id`. Its `covered_install_price_cents` is captured as the final quote's `grand_total_cents` at cure time, which is the basis for any future prorated payout. Its `term_months` defaults to 180 (fifteen years), and its `coverage_start_at` is set to the install job's `vehicle_traffic_ok_at` — the instant the floor was deemed cured.

A `Customer` files a **warranty claim** (a callback) against an active warranty, supplying the `defect_type`, which is one of `HOT_TIRE`, `PEEL`, or `OTHER`. Filing is allowed only while the warranty is `ACTIVE` and the logical clock is still within the coverage window — that is, the current instant is strictly before `coverage_start_at` plus `term_months`; a claim filed after coverage has lapsed is rejected with `ERR_COVERAGE_EXPIRED`. Filing creates the claim in `SUBMITTED` status, moves the warranty from `ACTIVE` to `CLAIM_OPEN`, and stamps the claim's `reported_at` at the logical clock's current instant. The claim's `warranty_id` records the warranty, its `revision_rounds` starts at 0, and its `prorated_credit_cents` starts at 0. The system also computes `months_elapsed`, the whole months (floored) from the warranty's `coverage_start_at` to the claim's `reported_at`.

A `WarrantyAgent` **reviews** a submitted claim by supplying an `action` of `REQUEST_INFO`, `APPROVE`, or `REJECT`. Requesting more information moves a `SUBMITTED` claim to `NEEDS_INFO`, parking it until the customer responds. The homeowner then **resubmits**, moving the claim from `NEEDS_INFO` back to `SUBMITTED` and incrementing `revision_rounds` by 1 to count the callback round — this `NEEDS_INFO → SUBMITTED` loop may repeat as many times as the back-and-forth requires.

Approving a `SUBMITTED` claim moves it to `APPROVED` but is permitted only when the `defect_type` is `HOT_TIRE` or `PEEL`; an `OTHER` defect cannot be approved for payout and an approval attempt on one is rejected with `ERR_DEFECT_NOT_COVERED`. On approval the system computes `prorated_credit_cents`. The remaining coverage is the warranty `term_months` minus the claim's `months_elapsed`, clamped at 0 so it never goes negative past term. The payout is the warranty's `covered_install_price_cents` multiplied by the ratio of remaining months to total `term_months`, multiplied by a defect factor, and rounded half up to whole cents. The defect factor is 1.00 for a `PEEL` claim — peel and delamination are treated as a full-coat failure and pay the full prorated amount — and 0.50 for a `HOT_TIRE` claim, since a hot-tire lift is a localized cosmetic defect; for the same covered price and the same elapsed months a hot-tire claim therefore pays exactly half what a peel claim pays. Rejecting a `SUBMITTED` claim instead moves it to `REJECTED`, leaves `prorated_credit_cents` at 0, and bubbles the warranty back from `CLAIM_OPEN` to `ACTIVE`.

An approved claim proceeds to scheduling: a `WarrantyAgent` **schedules the callback**, moving the claim from `APPROVED` to `CALLBACK_SCHEDULED`, and later **closes** it, moving it from `CALLBACK_SCHEDULED` to `CLOSED`. Closing a scheduled callback bubbles the warranty from `CLAIM_OPEN` back to `ACTIVE`, re-arming coverage for any future claim. The warranty returns to `ACTIVE` from `CLAIM_OPEN` whenever the open claim reaches a resting point with no other non-terminal claim outstanding — whether that resting point is a rejection or a closed callback. A requested transition attempted from a status that does not define it — closing a claim that was never scheduled, approving a claim that is not submitted, and so on — is rejected with `ERR_INVALID_STATE`.

### 3.8. Referral Conversion, Claw-Back, and Project Cancellation

The referral program settles only at the moments a build truly completes or unwinds. When a referred project's build track reaches `COMPLETE` (at mark-cured), a referral still in `PENDING` transitions to `CONVERTED`, and the referrer customer's `account_credit_balance_cents` rises by the credit amount of fifteen thousand cents. Conversely, if a referred project that had already converted is later cancelled, the referral moves from `CONVERTED` to `CLAWED_BACK` and the referrer's `account_credit_balance_cents` falls by the same fifteen thousand cents — a compensating reversal that keeps the conserved-credit invariant true. A referral that is still `PENDING` when its referred project's sales track is declined transitions to `EXPIRED` and issues no credit at all.

Project **cancellation** is an administrator action that drives the build track to `CANCELLED` and unwinds everything downstream. It is permitted only while the build track is at `PRE_BUILD`, `SCHEDULED`, or `CURING`; an attempt to cancel a project whose build track is already terminal at `COMPLETE` or `CANCELLED` is rejected with `ERR_PROJECT_NOT_CANCELLABLE`. The cancel is optimistic-concurrency guarded: the body's `expected_project_version` must match the project's current `version`, or it is rejected with `ERR_STALE_PROJECT_VERSION` (section 2.9). On a successful cancel, any install job on the project in `BOOKED` or `IN_PROGRESS` is moved to `CANCELLED`, which frees the crew's day for that date. If a warranty exists, it is moved to `VOID`, and any non-terminal claim on that warranty — in `SUBMITTED`, `NEEDS_INFO`, `APPROVED`, or `CALLBACK_SCHEDULED` — is force-closed to `CLOSED` with no payout, leaving its `prorated_credit_cents` at 0. If the project's referral had converted, it is clawed back as described above. The project `version` is incremented.

### 3.9. Reading the System

All six roles can read the resources within their remit, and reads never mutate state or advance any `version`. A coating system can be fetched directly, and its color options can be listed beneath it; a financing plan, a crew, and the crew's install jobs are similarly readable by those who book and operate them. A customer can be fetched — exposing its `referral_code` and `account_credit_balance_cents` — and a customer's projects and referrals can be listed; the referrals listing accepts an optional `role` query parameter to filter to referrals where the customer is the referrer versus the referred. A project can be fetched to read both its `sales_status` and `build_status` dimensions, its `version`, its `accepted_quote_id`, and its `referral_id`; its assessments, quotes, install jobs, and warranties can each be listed beneath it, and the quotes listing accepts an optional `variant` query parameter to restrict the list to estimates or finals. Individual quotes, install jobs, warranties, claims, and referrals are each directly fetchable, and a warranty's claims can be listed beneath it. All these list endpoints honor the `limit` and `offset` pagination parameters of section 2.3.

## 4. Endpoint Definitions

Operations that create a brand-new resource return a `201 Created` status code; operations that modify an existing resource — including the state-transition actions that drive the various workflows — return a `200 OK` status code. The logical-clock capability also returns `200 OK`. The request and response payloads for each endpoint are not repeated here; reconstruct them from the workflow narratives in section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/coating-systems` | Create a coating system | PlatformAdmin |
| GET | `/coating-systems/{id}` | Get a coating system | PlatformAdmin, SalesRep, Scheduler, WarrantyAgent, Customer |
| POST | `/color-options` | Create a color option under a coating system | PlatformAdmin |
| GET | `/coating-systems/{id}/color-options` | List color options belonging to a coating system | PlatformAdmin, SalesRep, Scheduler, WarrantyAgent, Customer |
| POST | `/financing-plans` | Create a financing plan | PlatformAdmin |
| POST | `/crews` | Create an install crew | PlatformAdmin |
| GET | `/crews/{id}` | Get a crew | PlatformAdmin, Scheduler |
| GET | `/crews/{id}/install-jobs` | List install jobs booked to a crew | PlatformAdmin, Scheduler |
| POST | `/customers` | Create a customer | PlatformAdmin, SalesRep |
| GET | `/customers/{id}` | Get a customer | PlatformAdmin, SalesRep, WarrantyAgent, Customer |
| GET | `/customers/{id}/projects` | List a customer's projects | PlatformAdmin, SalesRep, Customer |
| GET | `/customers/{id}/referrals` | List referrals where this customer is referrer or referred | PlatformAdmin, SalesRep, Customer |
| POST | `/projects` | Create a project | SalesRep |
| GET | `/projects/{id}` | Get a project | PlatformAdmin, SalesRep, Scheduler, WarrantyAgent, Customer |
| POST | `/projects/{id}/assessments` | Record an assessment; computes condition score, prep tier, billable crack feet | SalesRep |
| GET | `/projects/{id}/assessments` | List assessments on a project | PlatformAdmin, SalesRep, Scheduler |
| POST | `/projects/{id}/quotes` | Create an ESTIMATE quote from the approved assessment | SalesRep |
| GET | `/projects/{id}/quotes` | List quotes on a project, optionally filtered by variant | PlatformAdmin, SalesRep, Customer |
| GET | `/quotes/{id}` | Get a quote | PlatformAdmin, SalesRep, Scheduler, Customer |
| POST | `/quotes/{id}/send` | Send a draft quote to the customer | SalesRep |
| POST | `/quotes/{id}/accept` | Customer accepts a sent quote (OCC-guarded) | Customer |
| POST | `/projects/{id}/decline` | Customer declines the project | Customer |
| POST | `/projects/{id}/cancel` | Admin cancels a project (OCC-guarded) | PlatformAdmin |
| POST | `/projects/{id}/install-jobs` | Book the one-day install to a crew | Scheduler |
| GET | `/projects/{id}/install-jobs` | List install jobs on a project | PlatformAdmin, Scheduler, Crew |
| POST | `/install-jobs/{id}/start` | Crew starts the install | Crew |
| POST | `/install-jobs/{id}/complete` | Crew completes the install with on-site measurements | Crew |
| POST | `/install-jobs/{id}/mark-cured` | Scheduler marks the install cured after the cure deadline | Scheduler |
| GET | `/warranties/{id}` | Get a warranty | PlatformAdmin, WarrantyAgent, Customer |
| GET | `/projects/{id}/warranties` | List warranties on a project | PlatformAdmin, WarrantyAgent, Customer |
| POST | `/warranties/{id}/claims` | Customer files a warranty/callback claim | Customer |
| GET | `/warranties/{id}/claims` | List claims on a warranty | PlatformAdmin, WarrantyAgent, Customer |
| GET | `/claims/{id}` | Get a warranty claim | PlatformAdmin, WarrantyAgent, Customer |
| POST | `/claims/{id}/review` | Agent reviews a submitted claim (REQUEST_INFO / APPROVE / REJECT) | WarrantyAgent |
| POST | `/claims/{id}/resubmit` | Customer resubmits after a request for information | Customer |
| POST | `/claims/{id}/schedule-callback` | Agent schedules the repair callback | WarrantyAgent |
| POST | `/claims/{id}/close` | Agent closes a scheduled callback | WarrantyAgent |
| POST | `/referrals` | Create a referral | SalesRep |
| GET | `/referrals/{id}` | Get a referral | PlatformAdmin, SalesRep, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_COLOR_SYSTEM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SELF_REFERRAL` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SALES_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_CREW_NOT_METALLIC_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_CREW_DAY_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_SITE_CURE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CREW_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CURE_WINDOW_NOT_ELAPSED` | 409 Conflict |
| `ERR_INSTALL_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_COVERAGE_EXPIRED` | 409 Conflict |
| `ERR_DEFECT_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_FINANCING_PRINCIPAL_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_PROJECT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DECLINE_AFTER_SCHEDULED` | 409 Conflict |
