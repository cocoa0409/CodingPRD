# Sunroom & Patio Enclosure API — Product Requirements Document

## 1. Introduction

A sunroom or patio enclosure is rarely an off-the-shelf product. Each project begins with a homeowner's bare patio, travels through field measurement, design selection, municipal permitting, structural engineering, fabrication, weather-sensitive installation, and a final code inspection before a warranty is issued. This API exists to orchestrate that long, branching journey as a single auditable pipeline, so that every party — the homeowner, the sales designer, the municipal permit office, the fabrication shop, the field install team, and the code inspector — operates against one shared, consistent record of where each project stands.

Two characteristics make this domain demanding. First, money is committed in stages: a provisional estimate is priced at design time and the homeowner accepts it, but the binding price is only locked when fabrication begins, and a re-measurement can invalidate everything quoted beforehand. Second, several gates are genuinely safety- and law-bound rather than cosmetic — a structure cannot be built unless it is engineered to withstand the site's wind and snow loads, a permit cannot authorize a build after it has lapsed, and a crew cannot install in unsafe weather. The system therefore treats state transitions, price calculations, and scheduling constraints as first-class, strictly ordered rules. This document specifies those rules so that an implementation can reproduce them exactly.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly six roles: `Homeowner`, `SalesDesigner`, `PermitOfficer`, `Manufacturer`, `InstallManager`, and `Inspector`. If either header is missing, or if `X-User-Role` is not one of these six known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The `Homeowner` role is **entity-backed**: when `X-User-Role` is `Homeowner`, the `X-User-ID` is the `id` of the acting `Homeowner` entity. Ownership checks on any resource that traces back to a `Homeowner` compare that homeowner's identity to `X-User-ID`. Concretely, a `Project` references its owner through `homeowner_id`; a `Quote`, a `FinancingApplication`, and a `PermitApplication` each trace to a homeowner through their `project_id` (and a financing application also through its `quote_id`). When a `Homeowner` attempts to cancel a project, accept or reject a quote, submit a financing application, or resubmit a permit on a project they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The remaining five roles — `SalesDesigner`, `PermitOfficer`, `Manufacturer`, `InstallManager`, and `Inspector` — are **opaque** operator identities. When `X-User-Role` is any of these, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server accepts it for authentication and authorization but does not compare it against any entity's `id`. `SalesDesigner` registers homeowners and projects, records and accepts measurements, finalizes designs, issues estimate quotes, submits engineering reviews, and decides financing. `PermitOfficer` runs permit review, records HOA outcomes, rules on permits, and rules on engineering reviews. `Manufacturer` owns fabrication. `InstallManager` manages crews, schedules and runs installs, and schedules inspections. `Inspector` passes or fails inspections.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range from 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless stated otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Almost every resource in this system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded once when the resource is created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 on creation and increments by one on every subsequent mutation; it is the basis for optimistic concurrency control described in §2.6.

One entity is deliberately leaner: the `Warranty` is immutable once issued. It carries only `id` and `created_at`; it has no `updated_at` field and no `version` field, because nothing ever modifies a warranty after the inspection that creates it. All other entities — `Homeowner`, `Project`, `Measurement`, `Quote`, `FinancingApplication`, `PermitApplication`, `EngineeringReview`, `ManufactureOrder`, `InstallCrew`, `InstallJob`, and `Inspection` — carry the full set of `id`, `created_at`, `updated_at`, and `version`.

The `Project` is the spine of the pipeline, and its `version` is the most consequential. Every transition that advances or rewinds a project — accepting a measurement, finalizing a design, issuing the first quote, accepting a quote, approving the permit, creating a manufacture order, starting that order's production, scheduling an install, scheduling an inspection, passing or failing that inspection, and cancelling — increments `Project.version` by one and refreshes `Project.updated_at`. Several of these transitions are driven indirectly by an action on a child entity; the project's version still advances. Implementers should treat any change to a project's lifecycle as a project mutation.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many read endpoints are nested, exposing a child collection beneath a parent identifier — for example, a project's measurements, quotes, permit applications, manufacture orders, install jobs, inspections, and warranties, a quote's financing applications, a permit's engineering reviews, and a crew's install jobs. For any request, the system resolves every path identifier and every body foreign key left-to-right, in the order they appear, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the **first** identifier that does not resolve to an existing entity. A request for the engineering reviews of a non-existent permit therefore fails on the permit before the system ever considers the reviews. This existence pass runs after authentication and authorization but before any state or business validation.

### 2.6. Optimistic Concurrency on Quote Acceptance

Quote acceptance is the single operation in this system guarded by optimistic concurrency control. When a `Homeowner` accepts a quote, the request body must carry `expected_project_version`, a non-optional field holding the `version` of the owning `Project` as the client last observed it. The server compares `expected_project_version` against the project's current `version`; if they do not match, the acceptance is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

This guard exists because a project's version can advance between the moment a client reads the quote list and the moment it tries to accept. The most important case is a re-measurement: re-measuring a designed project supersedes every outstanding estimate and bumps `Project.version`. A client that loaded the quotes before that re-measurement and then attempts to accept a now-superseded quote would be acting on stale data; the version mismatch rejects the attempt before any damage is done. No other endpoint takes a version field, and no other endpoint performs this check.

### 2.7. Validation Ordering and Precedence

When an operation can fail several ways, checks are evaluated in a fixed precedence so that the reported error is deterministic. Authentication comes first: a missing or unknown user context yields `ERR_UNAUTHENTICATED` before anything else. Role authorization is second, yielding `ERR_FORBIDDEN_ROLE`. Resource-ownership for an entity-backed `Homeowner` is third, yielding `ERR_NOT_RESOURCE_OWNER`. Existence of every path id and body foreign key is fourth, yielding `ERR_NOT_FOUND`. State legality — whether the target entity is in a state from which the requested transition is allowed — is fifth, yielding `ERR_INVALID_STATE` (HTTP 409). The optimistic-concurrency check on quote acceptance is sixth, yielding `ERR_STALE_PROJECT_VERSION`. Only after these gates do the domain-specific business rules (engineering ratings, weather safety, crew certification and availability, scheduling windows, permit expiry and resubmission caps, HOA and engineering permit gates, financing principal and down-payment limits, and punchlist rules) apply. Request well-formedness — required body fields present and well-typed, enum values within their declared sets — is checked as `ERR_INVALID_REQUEST` (HTTP 400), and pagination bounds as `ERR_INVALID_PAGINATION` (HTTP 400).

### 2.8. Monetary Precision and Pinned Rounding

All prices are integers expressed in cents; there are no fractional-cent values stored or returned. Wherever a calculation produces a non-integer cent figure, it is rounded to a whole number of cents using **round half up** (a value exactly at the halfway point rounds away from zero). The footprint area calculation similarly rounds to two decimal places, round half up.

Two ordering pins matter for prices and must be respected exactly. First, the quote total is built in a fixed sequence: the base price is computed, then the add-ons total, then the tax, then the grand total — never in another order, because the total depends on the tax and the tax depends on the sum of base and add-ons. Second, sales tax is computed **once on the sum** of all taxable line items (base price plus add-ons) and then rounded a single time; it is never computed by rounding each line item's tax separately and summing those rounded amounts. The two approaches can differ by a cent, and only the sum-then-round result is correct.

### 2.9. Cascades, Reversions, and the Logical Clock

State changes frequently ripple beyond the entity directly addressed. Accepting a measurement copies dimensions onto the project and recomputes its footprint; a re-measurement supersedes the prior accepted measurement and every outstanding estimate; accepting a quote supersedes its siblings and points the project at the accepted quote; starting production issues a binding final quote that supersedes the accepted estimate; cancelling a project unwinds quotes, permits, and manufacture orders; an engineering failure can reject the permit it supports; and a failed inspection reopens the install job and rewinds the project. Each such cascade is specified in §3 within the workflow that triggers it. Every cascade that mutates the project advances `Project.version` and refreshes `Project.updated_at`.

Time-gated rules — permit expiry, manufacturing lead time, and warranty terms — are evaluated against a **logical clock**, not the wall clock. The server starts with the logical clock fixed at `2026-04-01T00:00:00Z`; before any explicit set, every time-dependent computation reads exactly this instant and never falls back to wall-clock time. A test-driving capability lets an authorized operator advance the logical clock to a supplied instant, provided in the `to_iso8601` field, after which all subsequent time computations use the new value. Permit expiry in particular is evaluated lazily: a permit's lapse into the expired state is recognized when it is next read or acted upon, by comparing the logical clock against its recorded expiry deadline.

## 3. Business Logic & Workflows

### 3.1. Homeowners, Projects, and the Design Loop

Everything starts with a `Homeowner` record, registered by a `SalesDesigner` with a login `email` (unique among homeowners and non-empty), a `full_name`, and three site attributes that will drive later engineering and permitting decisions: `hoa_governed` (whether the property sits inside an HOA-governed community, defaulting to false), `ground_snow_load_psf` (the site's ground snow load in pounds per square foot, which must be zero or greater), and `design_wind_speed_mph` (the site's design wind speed in miles per hour from the local wind map, which must be zero or greater).

A `SalesDesigner` then opens a `Project` for that owner, supplying `homeowner_id`, the `address_line` where the enclosure will be built, the `structure_type`, and the `material`. The `structure_type` is one of `SCREEN_ROOM`, `THREE_SEASON`, or `FOUR_SEASON`; the `material` is one of `ALUMINUM`, `VINYL`, or `THERMAL_BREAK_ALUMINUM`. A new project begins in `DRAFT` with `version` 1. Its measured dimensions — `width_in`, `depth_in`, and the derived `footprint_sqft` — all begin at 0 until a measurement is accepted, its `accepted_quote_id` begins null, and the two computed gating flags `requires_hoa` and `requires_engineering` both begin false. The project's lifecycle `status` walks the values `DRAFT`, `MEASURED`, `DESIGNED`, `QUOTED`, `PERMITTING`, `APPROVED_TO_BUILD`, `IN_MANUFACTURE`, `INSTALLING`, `INSPECTING`, `COMPLETED`, and `CANCELLED`.

Field measurement is captured as a `Measurement` against a project's `project_id`, recording the measured `width_in`, `depth_in`, and `wall_height_in` (each strictly greater than 0), plus `existing_slab` (whether a usable concrete slab already exists, defaulting to false). A new measurement is `PENDING`; its lifecycle `status` is one of `PENDING`, `ACCEPTED`, or `SUPERSEDED`. When a `SalesDesigner` accepts a `PENDING` measurement, the project must not be cancelled or completed and the measurement's `project_id` must match the target project. Acceptance flips the measurement to `ACCEPTED`, copies its `width_in` and `depth_in` onto the project, and recomputes the project's `footprint_sqft` as the width in inches multiplied by the depth in inches, divided by 144 (the number of square inches in a square foot), rounded half up to two decimal places. Accepting the project's first measurement advances the project from `DRAFT` to `MEASURED`.

Once measured, a `SalesDesigner` finalizes the design, which requires the project to be in `MEASURED` with both its `structure_type` and `material` set, and advances it `MEASURED → DESIGNED`. Finalization sets two flags. `requires_hoa` is set to a plain copy of the owning homeowner's `hoa_governed`. `requires_engineering` is set true if and only if any of the following holds: the `structure_type` is `FOUR_SEASON`, or the site's `ground_snow_load_psf` is strictly greater than 30, or the site's `design_wind_speed_mph` is at least 130. The boundaries are exact: a snow load of exactly 30.0 does not trigger engineering, whereas a wind speed of exactly 130 does.

The design loop is genuinely cyclic. A designer may re-measure a project that has already reached `DESIGNED` — whether it is still `DESIGNED` or has since advanced to `QUOTED` — by accepting a new `PENDING` measurement on it, which rewinds the project to `MEASURED` (`DESIGNED → MEASURED` or `QUOTED → MEASURED`) so the design can be re-finalized. This re-measure is only permitted while the project holds no accepted quote — that is, while `accepted_quote_id` is still null (which is the case in both `DESIGNED` and `QUOTED`, since accepting a quote advances the project to `PERMITTING`). When it happens, the prior `ACCEPTED` measurement is set to `SUPERSEDED`, the new one becomes `ACCEPTED`, the project's `width_in`, `depth_in`, and `footprint_sqft` are recomputed from it, and — critically — every `ISSUED` quote on the project is set to `SUPERSEDED`, because a re-measure invalidates any outstanding estimate. Each accept transition increments `Project.version` by one. A measurement that was `ACCEPTED` moves to `SUPERSEDED` only as a side effect of a newer measurement being accepted on the same project; that supersede carries no effect beyond the status flip itself.

A `Homeowner` may cancel a project while it sits in any non-terminal pre-build state — that is, while its status is `DRAFT`, `MEASURED`, `DESIGNED`, `QUOTED`, or `PERMITTING`. Cancellation drives the project to `CANCELLED`, sets all of its `ISSUED` quotes to `SUPERSEDED`, expires the project's permit application if one is currently `SUBMITTED` or `IN_REVIEW` (setting it to `EXPIRED`), cancels the project's manufacture order if one is `QUEUED` or `IN_PRODUCTION`, and increments `Project.version` by one. Any attempt to drive a transition from a state the entity is not in is rejected with `ERR_INVALID_STATE`.

### 3.2. Pricing a Quote: Estimate at Design, Final at Build

When a `SalesDesigner` issues the first quote for a `DESIGNED` project, the project advances `DESIGNED → QUOTED`. The act of quoting creates a `Quote` referencing the project's `project_id`, with a system-assigned `revision_no` (a 1-based counter equal to one more than the highest existing `revision_no` on the project, never less than 1) and a `variant` of `ESTIMATE`. The estimate is the provisional price the homeowner accepts at design time. A `Quote` carries a lifecycle `status` of `ISSUED`, `ACCEPTED`, `REJECTED`, or `SUPERSEDED`, beginning at `ISSUED`.

Every quote is priced through the same four computed money fields, in the pinned order base → add-ons → tax → total. The `base_price_cents` reflects structure, material, and area. A per-square-foot rate in cents is selected by `structure_type` — 4,500 cents for `SCREEN_ROOM`, 9,000 cents for `THREE_SEASON`, and 16,000 cents for `FOUR_SEASON`. A material multiplier expressed in thousandths is selected by `material` — 1,000 for `ALUMINUM`, 1,150 for `VINYL`, and 1,300 for `THERMAL_BREAK_ALUMINUM`. The base price is the project's current `footprint_sqft` multiplied by the per-square-foot rate, multiplied by the material multiplier, divided by 1,000, with the final product rounded half up to whole cents.

The `addons_cents` field is the sum of up to three line items, each added only when its condition holds. If the currently accepted measurement's `existing_slab` is false, a slab pour of 320,150 cents is added. If the project's `requires_engineering` is true, an engineering stamp of 95,075 cents is added. If the project's `requires_hoa` is true, an HOA filing fee of 25,033 cents is added. When none apply, the add-ons total is zero.

Sales tax is computed once on the sum of base and add-ons. The taxable amount is `base_price_cents` plus `addons_cents`; `tax_cents` is that taxable amount multiplied by the tax rate of 75 thousandths (7.5%), divided by 1,000, rounded half up to whole cents in a single rounding step. The grand total, `total_cents`, is `base_price_cents` plus `addons_cents` plus `tax_cents`. Issuing a quote increments `Project.version` by one.

The homeowner resolves an `ISSUED` quote one of two ways. Acceptance — which requires the quote to be `ISSUED`, to belong to the homeowner's project, and to pass the optimistic-concurrency check on `expected_project_version` described in §2.6 — sets the accepted quote to `ACCEPTED`, sets every other `ISSUED` quote on the project to `SUPERSEDED`, points `accepted_quote_id` at the accepted quote, advances the project `QUOTED → PERMITTING`, and increments `Project.version` by one. A version mismatch here yields `ERR_STALE_PROJECT_VERSION` (HTTP 412). Rejection, by contrast, requires only that the quote be `ISSUED`; it sets that quote to `REJECTED` and has no other effect — the project remains `QUOTED`, awaiting a new quote or a cancellation. A quote may also move from `ISSUED` to `SUPERSEDED` purely as a system side effect when a re-measure or a sibling acceptance invalidates it; that flip carries no further consequence.

### 3.3. Financing the Accepted Quote

After a quote is accepted, a `Homeowner` may finance it by submitting a `FinancingApplication`. The submission supplies `project_id`, `quote_id` (the accepted quote being financed, whose `total_cents` is the figure financed), `down_payment_cents` (the up-front amount, which must be zero or greater and reduces the principal), `term_months` (one of 12, 24, 36, or 60), and `credit_score` (the applicant's FICO score, between 300 and 850 inclusive). The `project_id` is the denormalized owning project, equal to the quote's project; reverse discovery of a quote's financing applications is offered through the quote. On submission the system computes `amount_financed_cents` as the accepted quote's `total_cents` minus `down_payment_cents`. A down payment greater than the accepted quote's `total_cents` would yield a negative principal and is rejected at submission with `ERR_DOWNPAYMENT_EXCEEDS_TOTAL` (HTTP 422). A new application begins in `SUBMITTED`; its `status` is one of `SUBMITTED`, `APPROVED`, or `DECLINED`.

A `SalesDesigner` then decides the application, a single decision endpoint that forks to one of two divergent outcomes. The application is **approved** when it is `SUBMITTED`, its `credit_score` is at least 650, and its `amount_financed_cents` is at most 7,500,000 cents. The application is **declined** when it is `SUBMITTED` but its `credit_score` is below 650 or its `amount_financed_cents` exceeds 7,500,000 cents. The two branches do genuinely different work and must be treated with equal care.

On the approval branch, two values are computed. The `apr_bps` (annual percentage rate in basis points) is selected by credit-score tier: a score of at least 760 earns 599 basis points; a score from 700 up to (but not including) 760 earns 999 basis points; a score from 650 up to (but not including) 700 earns 1,499 basis points. The cutoffs are inclusive at the bottom of each tier — a 700 score earns the 999-basis-point rate, not 1,499, and a 650 score is approvable at 1,499 basis points, whereas a 649 score is declined. Then `monthly_payment_cents` is computed by standard amortization in the pinned order principal → monthly rate → payment: the principal is `amount_financed_cents`; the monthly rate is `apr_bps` divided by 10,000 (converting basis points to a fraction) and then divided by 12; the term in months is `term_months`. If the monthly rate is zero, the monthly payment is the principal divided by the number of months, rounded half up to whole cents. Otherwise the payment is the principal multiplied by the amortization factor — the monthly rate times one plus the monthly rate raised to the power of the number of months, all divided by the quantity one plus the monthly rate raised to the power of the number of months minus one — with the result rounded half up to whole cents in a single final step.

On the decline branch, nothing is computed: the status simply becomes `DECLINED`, and `apr_bps` and `monthly_payment_cents` remain unset. When the decline is specifically caused by a principal above 7,500,000 cents, the underwriting attempt surfaces `ERR_PRINCIPAL_EXCEEDED` (HTTP 422).

### 3.4. Permitting, HOA Review, and Structural Engineering

Once a project reaches `PERMITTING`, a `SalesDesigner` or a `Homeowner` may submit a `PermitApplication` carrying `project_id` and the issuing `jurisdiction_code`. At submission the application copies the project's `requires_hoa` into its own `hoa_required` flag and sets its `hoa_status` accordingly: `NOT_REQUIRED` when HOA review is not needed, otherwise `PENDING`. The `hoa_status` is one of `NOT_REQUIRED`, `PENDING`, `HOA_APPROVED`, or `HOA_DENIED`. A new permit begins `SUBMITTED`, with a lifecycle `status` of `SUBMITTED`, `IN_REVIEW`, `REJECTED`, `APPROVED`, or `EXPIRED`, a `resubmission_count` of 0, and a null `expires_at`.

A `PermitOfficer` begins review, advancing the permit `SUBMITTED → IN_REVIEW`; if `hoa_required` is true and `hoa_status` is still `NOT_REQUIRED`, beginning review sets `hoa_status` to `PENDING`. The officer records the HOA outcome separately, setting `hoa_status` to either `HOA_APPROVED` or `HOA_DENIED`. The officer's ruling on the permit itself is a single decide operation taking an `outcome`. A decision of approval requires the permit to be `IN_REVIEW`; if `hoa_required` is true, `hoa_status` must be `HOA_APPROVED`, otherwise the approval is rejected with `ERR_HOA_NOT_APPROVED` (HTTP 409); and if the project's `requires_engineering` is true, there must exist a passed engineering review for this permit, otherwise the approval is rejected with `ERR_ENGINEERING_PENDING` (HTTP 409). On approval, the permit's `expires_at` is set to the logical clock now plus 180 days (the permit validity window), and the project advances `PERMITTING → APPROVED_TO_BUILD`, incrementing `Project.version` by one. A decision of rejection requires only that the permit be `IN_REVIEW`; it sets the permit to `REJECTED` and awaits resubmission, with no other effect.

The permit resubmission loop is cyclic. A `Homeowner` may resubmit a `REJECTED` permit, sending it `REJECTED → SUBMITTED`, provided its `resubmission_count` is below the cap of 3; resubmission increments `resubmission_count` by one. A resubmission attempted at or above 3 prior resubmissions is rejected with `ERR_RESUBMIT_LIMIT` (HTTP 409). Separately, an `APPROVED` permit lapses to `EXPIRED` when the logical clock reaches or passes its `expires_at` while the project is still `PERMITTING` or `APPROVED_TO_BUILD` and no manufacture order has yet been created; this lapse is evaluated lazily on read or transition and carries no effect beyond the status flip.

Structural engineering is captured as an `EngineeringReview`, submitted by a `SalesDesigner` against a `permit_application_id` (the permit it supports) and a denormalized `project_id`. On submission the review copies the required ratings from the homeowner: `required_wind_mph` from the homeowner's `design_wind_speed_mph` and `required_snow_psf` from the homeowner's `ground_snow_load_psf`. The submitter supplies the ratings the proposed structural design actually achieves — `rated_wind_mph` and `rated_snow_psf`, each zero or greater. A review begins `PENDING`; its `status` is one of `PENDING`, `PASSED`, or `FAILED`. A `PermitOfficer` rules on a `PENDING` review. It passes only when `rated_wind_mph` is at least `required_wind_mph` and `rated_snow_psf` is at least `required_snow_psf`; passing unblocks the permit's approval and has no other effect. It fails when `rated_wind_mph` is below `required_wind_mph` or `rated_snow_psf` is below `required_snow_psf`; an attempt to mark a review passed while it is underrated on either axis is rejected with `ERR_ENGINEERING_UNDERRATED` (HTTP 422). When a review fails and its linked permit is currently `IN_REVIEW`, the engineering failure cascades to reject the permit, setting it to `REJECTED`.

### 3.5. Manufacturing and the Final Quote Reconciliation

With the project `APPROVED_TO_BUILD` — a state that structurally guarantees a non-null `accepted_quote_id` — a `Manufacturer` creates a `ManufactureOrder` referencing `project_id` and the `quote_id` (the accepted quote at order time, discoverable through the owning project). Creation is blocked if the project's approved permit has lapsed: when the logical clock is at or past the permit's `expires_at`, the order is rejected with `ERR_PERMIT_EXPIRED` (HTTP 409). Otherwise a new order is created `QUEUED`, the project advances `APPROVED_TO_BUILD → IN_MANUFACTURE`, and `Project.version` increments by one. An order's `status` is one of `QUEUED`, `IN_PRODUCTION`, `READY`, or `CANCELLED`.

At creation the order computes its `lead_time_days` and `promised_ready_at`. The lead time begins at a material base — 21 days for `ALUMINUM`, 28 days for `VINYL`, and 35 days for `THERMAL_BREAK_ALUMINUM`. If the project's `footprint_sqft` is strictly greater than 200 square feet, 14 days are added (a footprint of exactly 200.00 does not surcharge). If the `structure_type` is `FOUR_SEASON`, a further 10 days are added. The `promised_ready_at` is the logical clock at order time plus that many lead-time days — the planning estimate stamped when the order is created.

When the `Manufacturer` starts production, the order moves `QUEUED → IN_PRODUCTION`, and the system performs the dual-variant reconciliation: it creates a new `FINAL`-variant `Quote` with `revision_no` one greater than the current highest, priced by the same base/add-ons/tax/total rules but recomputed against the currently accepted measurement, then supersedes the prior `ACCEPTED` quote and repoints `accepted_quote_id` to this final quote. Unlike an `ESTIMATE` (which begins at `ISSUED`), this `FINAL` quote is created directly in the `ACCEPTED` state — it becomes the project's new accepted (binding) quote — and the prior `ACCEPTED` quote (the estimate referenced by `accepted_quote_id`) is flipped to `SUPERSEDED`. If a re-measure changed the footprint between design and build, the final base price differs from the estimate; the final quote is the binding price. Marking the order `READY` requires it to be `IN_PRODUCTION` and records `ready_at` as the logical clock at that moment — the realized completion instant, which can diverge from `promised_ready_at` if the logical clock advanced by more or fewer days than the planned lead time. A `QUEUED` or `IN_PRODUCTION` order is cancelled, with only the status flip, when its project is cancelled.

### 3.6. Crews, Scheduling, and the Weather-Gated Install

Field installation is run by an `InstallManager`, who first registers each `InstallCrew` with a display `name`, a `max_wind_mph` (the maximum forecast wind speed, zero or greater, at which the crew will work), a `certified_four_season` flag (whether the crew may install `FOUR_SEASON` enclosures, defaulting to false), and an `active` flag (whether the crew is currently rostered for assignment, defaulting to true).

With the project `IN_MANUFACTURE` and its manufacture order `READY`, the manager schedules an `InstallJob` referencing the project's `project_id`, the assigned `crew_id`, a `scheduled_start` and `scheduled_end` defining a half-open window inclusive of the start and exclusive of the end, and a `forecast_wind_mph` (the forecast peak wind, zero or greater, for that window). Scheduling drives the project `IN_MANUFACTURE → INSTALLING`, creates the job with `progress_status` of `SCHEDULED` and `weather_status` of `CLEAR`, and increments `Project.version` by one. Several constraints guard scheduling, all checked at this point. The window must be valid: `scheduled_start` strictly before `scheduled_end`, otherwise `ERR_INVALID_WINDOW` (HTTP 422). The assigned crew must be active; an inactive crew yields `ERR_CREW_INACTIVE` (HTTP 422). A `FOUR_SEASON` project may only be assigned to a crew whose `certified_four_season` is true, otherwise `ERR_CREW_NOT_CERTIFIED` (HTTP 422). The crew must not be double-booked: no other non-terminal install job on the same crew may have a half-open window overlapping the requested half-open window, with no buffer or adjacency allowance — a job ending exactly when another begins does not conflict — and a violation yields `ERR_CREW_DOUBLE_BOOKED` (HTTP 409). Finally, the same project must observe a site-rest separation: no other non-terminal install job on the same project may have its window, expanded by 24 hours on both ends, intersect the requested window. This is a buffered, closed-interval rule (distinct from the crew's no-buffer half-open rule), so two visits to one site must be separated by at least 24 hours of rest; a violation yields `ERR_SITE_WINDOW_CONFLICT` (HTTP 409).

An install job carries two independent dimensions that evolve separately. The progress axis, `progress_status`, walks `SCHEDULED → IN_PROGRESS → INSTALLED`. The weather axis, `weather_status`, toggles between `CLEAR` and `WEATHER_HOLD`. The weather axis gates the progress transitions but is never changed by them, and progress transitions never touch the weather axis. The manager raises or releases a weather hold through the weather operation: a hold may be raised, moving `CLEAR → WEATHER_HOLD`, only while the weather is currently `CLEAR` and the progress is `SCHEDULED` or `IN_PROGRESS`; a hold is released, moving `WEATHER_HOLD → CLEAR`, only while the weather is currently `WEATHER_HOLD`. Either way only the weather axis moves; the progress axis is untouched.

Starting the install moves `progress_status` `SCHEDULED → IN_PROGRESS`. It requires the job to be `SCHEDULED`, the weather to be `CLEAR`, and the `forecast_wind_mph` to be at most the assigned crew's `max_wind_mph`. Completing the install moves `progress_status` `IN_PROGRESS → INSTALLED` and requires the job to be `IN_PROGRESS` with the weather `CLEAR`; completion enables the project's move into inspection. Both start and complete are blocked by unsafe weather: an attempt to start or complete while the weather is `WEATHER_HOLD`, or to start while the forecast wind exceeds the crew's `max_wind_mph`, is rejected with `ERR_WEATHER_UNSAFE` (HTTP 409).

### 3.7. Inspection, Punchlist Rework, and Warranty

Once the install job is `INSTALLED`, the `InstallManager` schedules a final `Inspection` referencing the project's `project_id` and the `install_job_id` of the completed job (the project's current install job, discoverable through the project). Scheduling drives the project `INSTALLING → INSPECTING`, creates the inspection in `SCHEDULED` with an `attempt_no` one greater than the highest existing attempt on the project (never less than 1), and increments `Project.version` by one. An inspection's `result` is one of `SCHEDULED`, `PASSED`, or `FAILED_PUNCHLIST`, and it records `punchlist_items` — the count of deficiencies logged on a failure, zero or greater, defaulting to 0.

An `Inspector` resolves a `SCHEDULED` inspection one of two ways. A pass requires the inspection to be `SCHEDULED` and the request to carry `punchlist_items` equal to 0; it sets the `result` to `PASSED`, drives the project `INSPECTING → COMPLETED`, issues the warranty described below, and increments `Project.version` by one. A failure requires the inspection to be `SCHEDULED` and the request to carry `punchlist_items` of at least 1; it sets the `result` to `FAILED_PUNCHLIST`, reopens the install job by setting its `progress_status` back to `IN_PROGRESS` for rework, drives the project `INSPECTING → INSTALLING`, and increments `Project.version` by one. The punchlist count is the discriminator: a fail submitted with fewer than one punchlist item is rejected with `ERR_PUNCHLIST_REQUIRED` (HTTP 422), which equally guards the symmetric expectation that a pass carries zero punchlist items. The cycle can repeat — a failed inspection sends the project back to `INSTALLING` for rework and a fresh inspection on the next attempt.

A passing inspection issues a `Warranty` for the project. The warranty references the completed project's `project_id` and copies the project's `structure_type` at issuance, which selects the coverage term: `term_years` is 1 year for a `SCREEN_ROOM`, 5 years for a `THREE_SEASON`, and 10 years for a `FOUR_SEASON`. Its `starts_at` is the moment of completion (the inspection pass time, read from the logical clock), and its `expires_at` is `starts_at` plus the term in years multiplied by 365 days, computed to the day. As noted in §2.4, the warranty is immutable: it carries only `id` and `created_at`, with no `updated_at` and no `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all action and state-transition endpoints — return `200 OK`. The logical-clock test-driving operation returns `200 OK` with no resource payload.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/homeowners` | Register a homeowner | SalesDesigner |
| POST | `/projects` | Create a project in DRAFT for a homeowner | SalesDesigner |
| GET | `/projects` | List projects, filterable by homeowner_id and status | SalesDesigner, Homeowner, InstallManager |
| GET | `/projects/{id}` | Fetch a project | SalesDesigner, Homeowner, InstallManager, Manufacturer, PermitOfficer, Inspector |
| POST | `/projects/{id}/finalize-design` | Lock design; compute requires_engineering and requires_hoa | SalesDesigner |
| POST | `/projects/{id}/cancel` | Cancel a non-terminal pre-build project (cascades) | Homeowner |
| GET | `/projects/{id}/measurements` | List a project's measurements | SalesDesigner, Homeowner |
| GET | `/projects/{id}/quotes` | List a project's quotes | SalesDesigner, Homeowner |
| GET | `/projects/{id}/permit-applications` | List a project's permit applications | SalesDesigner, Homeowner, PermitOfficer |
| GET | `/projects/{id}/manufacture-orders` | List a project's manufacture orders | Manufacturer, InstallManager, SalesDesigner |
| GET | `/projects/{id}/install-jobs` | List a project's install jobs | InstallManager, SalesDesigner, Inspector |
| GET | `/projects/{id}/inspections` | List a project's inspections | Inspector, InstallManager, SalesDesigner |
| GET | `/projects/{id}/warranties` | List a project's warranties | Homeowner, SalesDesigner, Inspector |
| POST | `/measurements` | Record a field measurement (PENDING) for a project | SalesDesigner |
| POST | `/measurements/{id}/accept` | Accept a PENDING measurement | SalesDesigner |
| POST | `/quotes` | Issue an ESTIMATE quote for a DESIGNED project | SalesDesigner |
| GET | `/quotes/{id}` | Fetch a quote | SalesDesigner, Homeowner |
| GET | `/quotes/{id}/financing-applications` | List a quote's financing applications | SalesDesigner, Homeowner |
| POST | `/quotes/{id}/accept` | Homeowner accepts an ISSUED quote (OCC on Project.version) | Homeowner |
| POST | `/quotes/{id}/reject` | Homeowner rejects an ISSUED quote | Homeowner |
| POST | `/financing-applications` | Submit a financing application against an accepted quote | Homeowner |
| POST | `/financing-applications/{id}/decide` | Decide a financing application: APPROVED or DECLINED | SalesDesigner |
| POST | `/permit-applications` | Submit a building permit application for a PERMITTING project | SalesDesigner, Homeowner |
| GET | `/permit-applications/{id}` | Fetch a permit application (lazily evaluates EXPIRED) | SalesDesigner, Homeowner, PermitOfficer |
| GET | `/permit-applications/{id}/engineering-reviews` | List a permit's engineering reviews | SalesDesigner, PermitOfficer |
| POST | `/permit-applications/{id}/begin-review` | Begin permit review (SUBMITTED → IN_REVIEW) | PermitOfficer |
| POST | `/permit-applications/{id}/hoa-decision` | Record the HOA review outcome | PermitOfficer |
| POST | `/permit-applications/{id}/decide` | Rule on the permit: APPROVED or REJECTED | PermitOfficer |
| POST | `/permit-applications/{id}/resubmit` | Resubmit a REJECTED permit (capped) | Homeowner |
| POST | `/engineering-reviews` | Submit a structural engineering review for a permit | SalesDesigner |
| POST | `/engineering-reviews/{id}/rule` | Rule PASSED or FAILED on an engineering review | PermitOfficer |
| POST | `/manufacture-orders` | Create a manufacture order for an APPROVED_TO_BUILD project | Manufacturer |
| POST | `/manufacture-orders/{id}/start` | Start production; issue the FINAL quote | Manufacturer |
| POST | `/manufacture-orders/{id}/ready` | Mark the build READY | Manufacturer |
| POST | `/crews` | Register an install crew | InstallManager |
| GET | `/crews/{id}` | Fetch an install crew | InstallManager |
| GET | `/crews/{id}/install-jobs` | List a crew's install jobs | InstallManager, SalesDesigner |
| POST | `/install-jobs` | Schedule an install for an IN_MANUFACTURE project | InstallManager |
| POST | `/install-jobs/{id}/start` | Begin installation (SCHEDULED → IN_PROGRESS) | InstallManager |
| POST | `/install-jobs/{id}/weather` | Set the independent weather axis (hold or clear) | InstallManager |
| POST | `/install-jobs/{id}/complete` | Finish installation (IN_PROGRESS → INSTALLED) | InstallManager |
| POST | `/inspections` | Schedule a final inspection for an INSTALLING project | InstallManager |
| POST | `/inspections/{id}/pass` | Pass the inspection; issue warranty; COMPLETED | Inspector |
| POST | `/inspections/{id}/fail` | Fail the inspection with a punchlist; reopen install | Inspector |
| POST | `/_clock/set_current_utc` | Set the logical clock for deterministic time-gated rules | SalesDesigner, InstallManager, Manufacturer, PermitOfficer, Inspector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_ENGINEERING_UNDERRATED` | 422 Unprocessable Entity |
| `ERR_ENGINEERING_PENDING` | 409 Conflict |
| `ERR_HOA_NOT_APPROVED` | 409 Conflict |
| `ERR_WEATHER_UNSAFE` | 409 Conflict |
| `ERR_CREW_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_CREW_INACTIVE` | 422 Unprocessable Entity |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_SITE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_PERMIT_EXPIRED` | 409 Conflict |
| `ERR_RESUBMIT_LIMIT` | 409 Conflict |
| `ERR_PRINCIPAL_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DOWNPAYMENT_EXCEEDS_TOTAL` | 422 Unprocessable Entity |
| `ERR_PUNCHLIST_REQUIRED` | 422 Unprocessable Entity |
